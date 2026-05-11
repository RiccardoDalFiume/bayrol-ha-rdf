"""Support for Bayrol binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BAYROL_DEVICE_ID, BAYROL_DEVICE_TYPE, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bayrol binary sensor entities."""
    mqtt_manager = hass.data[DOMAIN][config_entry.entry_id]["mqtt_manager"]
    async_add_entities([BayrolDeviceOnlineBinarySensor(config_entry, mqtt_manager)])


class BayrolDeviceOnlineBinarySensor(BinarySensorEntity):
    """Representation of Bayrol device online/offline status."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "device_online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, config_entry: ConfigEntry, mqtt_manager) -> None:
        """Initialize the Bayrol device online binary sensor."""
        self._config_entry = config_entry
        self._mqtt_manager = mqtt_manager
        self._attr_unique_id = f"{config_entry.entry_id}_device_online"
        self._attr_available = mqtt_manager.is_connected
        self._attr_is_on = mqtt_manager.device_online

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to Home Assistant."""
        self._mqtt_manager.register_availability_callback(self._handle_availability)
        self._mqtt_manager.register_device_online_callback(self._handle_device_online)
        self._handle_availability(self._mqtt_manager.is_connected)
        self._handle_device_online(self._mqtt_manager.device_online)

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is removed from Home Assistant."""
        self._mqtt_manager.unregister_availability_callback(self._handle_availability)
        self._mqtt_manager.unregister_device_online_callback(self._handle_device_online)

    def _handle_availability(self, is_available: bool) -> None:
        """Handle MQTT availability updates."""
        self._attr_available = is_available
        self.schedule_update_ha_state()

    def _handle_device_online(self, is_online: bool | None) -> None:
        """Handle Bayrol device online/offline updates."""
        self._attr_is_on = is_online
        self.schedule_update_ha_state()

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
