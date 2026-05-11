"""Support for Bayrol select entities."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    DOMAIN,
    SENSOR_TYPES_AUTOMATIC_SALT,
    SENSOR_TYPES_AUTOMATIC_CL_PH,
    SENSOR_TYPES_PM5_CHLORINE,
    BAYROL_DEVICE_ID,
    BAYROL_DEVICE_TYPE,
    AUTOMATIC_MQTT_TO_TEXT_MAPPING,
    PM5_MQTT_TO_TEXT_MAPPING,
    AUTOMATIC_TEXT_TO_MQTT_MAPPING,
    PM5_TEXT_TO_MQTT_MAPPING,
    CONF_OPTIONAL_CONTROLS_POLICY,
    OPTIONAL_CONTROLS_POLICY_AUTO,
    OPTIONAL_CONTROLS_POLICY_HIDE_ALL,
    OPTIONAL_CONTROLS_POLICY_SHOW_ALL,
    SMART_EASY_DETECTOR_TOPICS,
    SMART_EASY_DISABLED_VALUES,
    SMART_EASY_ENABLED_VALUES,
    SMART_EASY_OPTIONAL_CONTROL_TOPICS,
    INTERNAL_GUI_STATE_TOPICS,
)

_LOGGER = logging.getLogger(__name__)


async def _detect_smart_easy_optional_controls(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    mqtt_manager,
    timeout_seconds: float = 8.0,
) -> tuple[bool, dict[str, Any]]:
    """Detect whether optional Smart&Easy controls are available."""
    detector_values: dict[str, str] = {}
    optional_topics_seen: set[str] = set()
    first_message_received = asyncio.Event()

    def _on_topic_value(topic: str):
        def _callback(value: Any) -> None:
            value_str = str(value)
            if topic in SMART_EASY_DETECTOR_TOPICS:
                detector_values[topic] = value_str
            if topic in SMART_EASY_OPTIONAL_CONTROL_TOPICS:
                optional_topics_seen.add(topic)
            first_message_received.set()

        return _callback

    probe_topics = [*SMART_EASY_DETECTOR_TOPICS, *sorted(SMART_EASY_OPTIONAL_CONTROL_TOPICS)]
    for topic in probe_topics:
        mqtt_manager.subscribe(topic, _on_topic_value(topic))

    if mqtt_manager.is_connected:
        for topic in probe_topics:
            request_topic = f"d02/{config_entry.data[BAYROL_DEVICE_ID]}/g/{topic}"
            await hass.async_add_executor_job(mqtt_manager.publish, request_topic, "")

    try:
        await asyncio.wait_for(first_message_received.wait(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        pass

    detector_enabled = any(value in SMART_EASY_ENABLED_VALUES for value in detector_values.values())
    detector_disabled = (
        detector_values
        and all(value in SMART_EASY_DISABLED_VALUES for value in detector_values.values())
        and not detector_enabled
    )
    include_optional = detector_enabled or bool(optional_topics_seen)
    if detector_disabled and not optional_topics_seen:
        include_optional = False

    detection_info = {
        "policy": OPTIONAL_CONTROLS_POLICY_AUTO,
        "detector_values": detector_values,
        "optional_topics_seen": sorted(optional_topics_seen),
        "include_optional_controls": include_optional,
        "reason": (
            "detector_enabled"
            if detector_enabled
            else "optional_topics_seen"
            if optional_topics_seen
            else "detector_disabled"
            if detector_disabled
            else "no_optional_signal"
        ),
    }
    return include_optional, detection_info


def _handle_select_value(select, value):
    """Handle incoming select value."""
    _LOGGER.debug("Received MQTT value: %s for select: %s", value, select._attr_name)
    _LOGGER.debug("Available options: %s", select._attr_options)

    resolved_option: str | None = None

    # Try to find the value in the device-specific mappings and store the TEXT value
    if select._config_entry.data[BAYROL_DEVICE_TYPE] == "PM5 Chlorine":
        if str(value) in PM5_MQTT_TO_TEXT_MAPPING:
            resolved_option = PM5_MQTT_TO_TEXT_MAPPING[str(value)]
            _LOGGER.debug("PM5 mapping found: %s -> %s", value, resolved_option)
        else:
            # Try coefficient conversion for numeric values
            resolved_option = _handle_numeric_value(select, value)
    elif (
        select._config_entry.data[BAYROL_DEVICE_TYPE] == "Automatic Cl-pH"
        or select._config_entry.data[BAYROL_DEVICE_TYPE] == "Automatic SALT"
    ):
        if str(value) in AUTOMATIC_MQTT_TO_TEXT_MAPPING:
            resolved_option = AUTOMATIC_MQTT_TO_TEXT_MAPPING[str(value)]
            _LOGGER.debug("Automatic mapping found: %s -> %s", value, resolved_option)
        else:
            # Try coefficient conversion for numeric values
            resolved_option = _handle_numeric_value(select, value)
    else:
        _LOGGER.warning("Unknown device type: %s", select._config_entry.data[BAYROL_DEVICE_TYPE])
        resolved_option = _handle_numeric_value(select, value)

    if resolved_option in select.options:
        select._attr_current_option = resolved_option
        select._last_unmapped_value = None
    else:
        select._last_unmapped_value = str(value)
        _LOGGER.debug(
            "Value %s for %s does not match options, keeping previous option %s",
            value,
            select._attr_name,
            select._attr_current_option,
        )

    _LOGGER.debug("Set current_option to: %s", select._attr_current_option)
    if select.hass is not None:
        select.schedule_update_ha_state()


def _handle_numeric_value(select, value):
    """Handle numeric values using coefficient conversion."""
    try:
        coefficient = select._select_config.get("coefficient")
        if coefficient is not None and coefficient != -1:
            converted_value = float(value) / coefficient
            _LOGGER.debug(
                "Converted value using coefficient %s: %s -> %s",
                coefficient,
                value,
                converted_value,
            )

            # Find the closest option
            if coefficient == 1:
                converted_value = int(converted_value)
                options = [int(opt) for opt in select._attr_options]
            else:
                converted_value = float(converted_value)
                options = [float(opt) for opt in select._attr_options]

            closest_option = min(options, key=lambda x: abs(x - converted_value))
            resolved_option = str(closest_option)
            _LOGGER.debug("Found closest option: %s", closest_option)
        else:
            # No coefficient, use value directly
            resolved_option = str(value)
    except (ValueError, TypeError) as e:
        _LOGGER.warning("Error converting value %s: %s", value, e)
        resolved_option = str(value)
    return resolved_option


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Bayrol select entities."""
    entities = []
    device_type = config_entry.data[BAYROL_DEVICE_TYPE]
    _LOGGER.debug("device_type: %s", device_type)

    # Get the entry-specific MQTT manager
    mqtt_manager = hass.data[DOMAIN][config_entry.entry_id]["mqtt_manager"]
    optional_policy = config_entry.options.get(CONF_OPTIONAL_CONTROLS_POLICY, OPTIONAL_CONTROLS_POLICY_AUTO)
    optional_runtime_info: dict[str, Any] = {"policy": optional_policy}
    include_optional_controls = True

    if device_type == "Automatic SALT":
        if optional_policy == OPTIONAL_CONTROLS_POLICY_HIDE_ALL:
            include_optional_controls = False
            optional_runtime_info.update(
                {
                    "include_optional_controls": False,
                    "reason": "policy_hide_all",
                }
            )
        elif optional_policy == OPTIONAL_CONTROLS_POLICY_SHOW_ALL:
            include_optional_controls = True
            optional_runtime_info.update(
                {
                    "include_optional_controls": True,
                    "reason": "policy_show_all",
                }
            )
        else:
            include_optional_controls, detection_info = await _detect_smart_easy_optional_controls(
                hass,
                config_entry,
                mqtt_manager,
            )
            optional_runtime_info.update(detection_info)

    if device_type == "Automatic SALT":
        for select_type, select_config in SENSOR_TYPES_AUTOMATIC_SALT.items():
            if select_config.get("entity_type") == "select":
                if select_type in INTERNAL_GUI_STATE_TOPICS:
                    continue
                if select_type in SMART_EASY_OPTIONAL_CONTROL_TOPICS and not include_optional_controls:
                    continue
                topic = select_type
                select = BayrolSelect(config_entry, select_type, select_config, topic, mqtt_manager)
                mqtt_manager.subscribe(topic, lambda v, s=select: _handle_select_value(s, v))
                entities.append(select)
    elif device_type == "Automatic Cl-pH":
        for select_type, select_config in SENSOR_TYPES_AUTOMATIC_CL_PH.items():
            if select_config.get("entity_type") == "select":
                topic = select_type
                select = BayrolSelect(config_entry, select_type, select_config, topic, mqtt_manager)
                mqtt_manager.subscribe(topic, lambda v, s=select: _handle_select_value(s, v))
                entities.append(select)
    elif device_type == "PM5 Chlorine":
        for select_type, select_config in SENSOR_TYPES_PM5_CHLORINE.items():
            if select_config.get("entity_type") == "select":
                topic = select_type
                select = BayrolSelect(config_entry, select_type, select_config, topic, mqtt_manager)
                mqtt_manager.subscribe(topic, lambda v, s=select: _handle_select_value(s, v))
                entities.append(select)

    hass.data[DOMAIN][config_entry.entry_id]["optional_controls"] = optional_runtime_info
    async_add_entities(entities)


class BayrolSelect(SelectEntity):
    """Representation of a Bayrol select entity."""

    def __init__(self, config_entry, select_type, select_config, topic, mqtt_manager):
        """Initialize the select entity."""
        self._config_entry = config_entry
        self._select_type = select_type
        self._select_config = select_config
        self._state_topic = topic
        self._mqtt_manager = mqtt_manager
        self._attr_name = select_config.get("name", select_type)
        self._attr_unique_id = f"{config_entry.entry_id}_{select_type}"
        self._attr_current_option = None
        self._attr_available = mqtt_manager.is_connected
        self._last_unmapped_value: str | None = None

        # Get options from config and convert to strings
        self._attr_options = [str(opt) for opt in select_config.get("options", [])]

        # Create custom mappings if provided
        self._mqtt_to_value = {}
        if "mqtt_values" in select_config:
            self._mqtt_to_value = select_config["mqtt_values"]

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to Home Assistant."""
        self._mqtt_manager.register_availability_callback(self._handle_availability)
        self._handle_availability(self._mqtt_manager.is_connected)

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is removed from Home Assistant."""
        self._mqtt_manager.unregister_availability_callback(self._handle_availability)

    def _handle_availability(self, is_available: bool) -> None:
        """Handle MQTT availability updates."""
        self._attr_available = is_available
        self.schedule_update_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        _LOGGER.debug("User selected option: %s", option)

        # Convert display text back to MQTT value based on device type
        mqtt_value = None

        if self._config_entry.data[BAYROL_DEVICE_TYPE] == "PM5 Chlorine":
            # Use PM5 specific mappings
            if option in PM5_TEXT_TO_MQTT_MAPPING:
                mqtt_value = PM5_TEXT_TO_MQTT_MAPPING[option]
                _LOGGER.debug("PM5 text mapping: %s -> %s", option, mqtt_value)
        elif (
            self._config_entry.data[BAYROL_DEVICE_TYPE] == "Automatic Cl-pH"
            or self._config_entry.data[BAYROL_DEVICE_TYPE] == "Automatic SALT"
        ):
            # Use Automatic specific mappings
            if option in AUTOMATIC_TEXT_TO_MQTT_MAPPING:
                mqtt_value = AUTOMATIC_TEXT_TO_MQTT_MAPPING[option]
                _LOGGER.debug("Automatic text mapping: %s -> %s", option, mqtt_value)

        if mqtt_value is None:
            # If no text mapping found, try coefficient conversion for numeric options
            try:
                coefficient = self._select_config.get("coefficient")
                if coefficient is not None and coefficient != -1:
                    # Convert display value to MQTT value
                    display_float = float(option)
                    mqtt_value = str(int(display_float * coefficient))
                    _LOGGER.debug(
                        "Converted display value %s to MQTT value %s using coefficient %s",
                        option,
                        mqtt_value,
                        coefficient,
                    )
                else:
                    # No coefficient, use option as MQTT value directly
                    mqtt_value = option
                    _LOGGER.debug("Using option as MQTT value directly: %s", mqtt_value)
            except (ValueError, TypeError) as e:
                _LOGGER.error("Error converting option %s to MQTT value: %s", option, e)
                return

        # Verify the option is valid
        # For text mappings, check if the MQTT value is in options
        # For numeric options, check if the original option is in options
        if mqtt_value in self._attr_options:
            # This is a text mapping case (like Production Rate)
            _LOGGER.debug("Text mapping case: MQTT value %s found in options", mqtt_value)
        elif option in self._attr_options:
            # This is a numeric case (like Salt Level)
            _LOGGER.debug("Numeric case: option %s found in options", option)
        else:
            _LOGGER.error(
                "Invalid option: %s (MQTT value: %s). Available options: %s",
                option,
                mqtt_value,
                self._attr_options,
            )
            return

        # Update the current option to the TEXT value (user's selection)
        self._attr_current_option = option

        # Publish the new value to the MQTT topic
        topic = f"d02/{self._config_entry.data[BAYROL_DEVICE_ID]}/s/{self._state_topic}"
        payload = f'{{"t":"{self._state_topic}","v":{mqtt_value}}}'
        await self.hass.async_add_executor_job(self._mqtt_manager.publish, topic, payload)
        _LOGGER.debug("Published MQTT message: %s", payload)

    @property
    def options(self) -> list[str]:
        """Return a list of available options."""
        # Convert MQTT values to display text based on device type
        display_options = []
        for option in self._attr_options:
            # Convert option to string for mapping lookup
            option_str = str(option)

            if self._config_entry.data[BAYROL_DEVICE_TYPE] == "PM5 Chlorine":
                # Use PM5 specific mappings
                if option_str in PM5_MQTT_TO_TEXT_MAPPING:
                    display_options.append(PM5_MQTT_TO_TEXT_MAPPING[option_str])
                else:
                    display_options.append(option_str)
            elif (
                self._config_entry.data[BAYROL_DEVICE_TYPE] == "Automatic Cl-pH"
                or self._config_entry.data[BAYROL_DEVICE_TYPE] == "Automatic SALT"
            ):
                # Use Automatic specific mappings
                if option_str in AUTOMATIC_MQTT_TO_TEXT_MAPPING:
                    display_options.append(AUTOMATIC_MQTT_TO_TEXT_MAPPING[option_str])
                else:
                    display_options.append(option_str)
            else:
                # Unknown device type - this should not happen
                _LOGGER.warning(
                    "Unknown device type: %s. Cannot map option: %s",
                    self._config_entry.data[BAYROL_DEVICE_TYPE],
                    option_str,
                )
                display_options.append(option_str)
        return display_options

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return extra state attributes for diagnostics in UI."""
        if self._last_unmapped_value is None:
            return {}
        return {"last_unmapped_value": self._last_unmapped_value}

    @property
    def device_info(self) -> DeviceInfo:
        """Device info."""
        device_id = self._config_entry.data[BAYROL_DEVICE_ID]
        return DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=f"Bayrol {device_id}",
            manufacturer="Bayrol",
            model=self._config_entry.data[BAYROL_DEVICE_TYPE],
        )
