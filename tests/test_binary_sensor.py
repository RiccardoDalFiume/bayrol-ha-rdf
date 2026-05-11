"""Unit tests for Bayrol binary sensor platform."""

from __future__ import annotations

import asyncio
from types import ModuleType, SimpleNamespace
import sys


def _ensure_homeassistant_stubs() -> None:
    """Provide minimal Home Assistant stubs required for module imports."""
    if "homeassistant" not in sys.modules:
        homeassistant_module = ModuleType("homeassistant")
        homeassistant_module.__path__ = []
        sys.modules["homeassistant"] = homeassistant_module

    if "homeassistant.core" not in sys.modules:
        core_module = ModuleType("homeassistant.core")
        core_module.HomeAssistant = object
        sys.modules["homeassistant.core"] = core_module

    if "homeassistant.config_entries" not in sys.modules:
        config_entries_module = ModuleType("homeassistant.config_entries")
        config_entries_module.ConfigEntry = object
        sys.modules["homeassistant.config_entries"] = config_entries_module

    if "homeassistant.components" not in sys.modules:
        components_module = ModuleType("homeassistant.components")
        components_module.__path__ = []
        sys.modules["homeassistant.components"] = components_module

    if "homeassistant.components.binary_sensor" not in sys.modules:
        binary_sensor_module = ModuleType("homeassistant.components.binary_sensor")

        class BinarySensorEntity:
            """Minimal binary sensor entity stub."""

            def __init__(self) -> None:
                self._attr_available = True
                self._attr_is_on = None

            @property
            def available(self):
                return self._attr_available

            @property
            def is_on(self):
                return self._attr_is_on

            def schedule_update_ha_state(self):
                self.update_calls = getattr(self, "update_calls", 0) + 1

        class BinarySensorDeviceClass:
            """Minimal device class stub."""

            CONNECTIVITY = "connectivity"

        binary_sensor_module.BinarySensorEntity = BinarySensorEntity
        binary_sensor_module.BinarySensorDeviceClass = BinarySensorDeviceClass
        sys.modules["homeassistant.components.binary_sensor"] = binary_sensor_module

    if "homeassistant.helpers" not in sys.modules:
        helpers_module = ModuleType("homeassistant.helpers")
        helpers_module.__path__ = []
        sys.modules["homeassistant.helpers"] = helpers_module

    if "homeassistant.helpers.device_registry" not in sys.modules:
        device_registry_module = ModuleType("homeassistant.helpers.device_registry")
        device_registry_module.DeviceInfo = dict
        sys.modules["homeassistant.helpers.device_registry"] = device_registry_module

    if "homeassistant.helpers.entity_platform" not in sys.modules:
        entity_platform_module = ModuleType("homeassistant.helpers.entity_platform")
        entity_platform_module.AddEntitiesCallback = object
        sys.modules["homeassistant.helpers.entity_platform"] = entity_platform_module

    if "homeassistant.components.sensor" not in sys.modules:
        sensor_module = ModuleType("homeassistant.components.sensor")

        class _DynamicEnum:
            def __getattr__(self, name):
                return name

        sensor_module.SensorDeviceClass = _DynamicEnum()
        sensor_module.SensorStateClass = _DynamicEnum()
        sys.modules["homeassistant.components.sensor"] = sensor_module


_ensure_homeassistant_stubs()

from custom_components.bayrol.binary_sensor import (  # noqa: E402
    BayrolDeviceOnlineBinarySensor,
    async_setup_entry,
)
from custom_components.bayrol.const import (  # noqa: E402
    BAYROL_DEVICE_ID,
    BAYROL_DEVICE_TYPE,
    DOMAIN,
)


class _FakeMQTTManager:
    """Fake MQTT manager for binary sensor tests."""

    def __init__(self, *, is_connected=False, device_online=None):
        self.is_connected = is_connected
        self.device_online = device_online
        self._availability_callbacks = set()
        self._device_online_callbacks = set()

    def register_availability_callback(self, callback):
        self._availability_callbacks.add(callback)

    def unregister_availability_callback(self, callback):
        self._availability_callbacks.discard(callback)

    def register_device_online_callback(self, callback):
        self._device_online_callbacks.add(callback)

    def unregister_device_online_callback(self, callback):
        self._device_online_callbacks.discard(callback)

    def emit_availability(self, value: bool):
        self.is_connected = value
        for callback in list(self._availability_callbacks):
            callback(value)

    def emit_device_online(self, value: bool | None):
        self.device_online = value
        for callback in list(self._device_online_callbacks):
            callback(value)


def _build_config_entry():
    return SimpleNamespace(
        entry_id="entry-1",
        data={
            BAYROL_DEVICE_ID: "device-123",
            BAYROL_DEVICE_TYPE: "Automatic SALT",
        },
    )


def test_async_setup_entry_creates_device_online_binary_sensor():
    """async_setup_entry should add the Bayrol device online entity."""
    mqtt_manager = _FakeMQTTManager(is_connected=True, device_online=True)
    config_entry = _build_config_entry()
    hass = SimpleNamespace(
        data={DOMAIN: {config_entry.entry_id: {"mqtt_manager": mqtt_manager}}},
    )
    added_entities = []

    asyncio.run(async_setup_entry(hass, config_entry, added_entities.extend))

    assert len(added_entities) == 1
    entity = added_entities[0]
    assert isinstance(entity, BayrolDeviceOnlineBinarySensor)
    assert entity._attr_unique_id == "entry-1_device_online"
    assert entity.is_on is True
    assert entity.available is True


def test_binary_sensor_tracks_availability_and_device_online_callbacks():
    """Entity should react to manager callback updates."""
    mqtt_manager = _FakeMQTTManager(is_connected=False, device_online=None)
    entity = BayrolDeviceOnlineBinarySensor(_build_config_entry(), mqtt_manager)

    asyncio.run(entity.async_added_to_hass())

    assert entity.available is False
    assert entity.is_on is None

    mqtt_manager.emit_availability(True)
    mqtt_manager.emit_device_online(True)
    mqtt_manager.emit_device_online(False)

    assert entity.available is True
    assert entity.is_on is False
    assert entity.update_calls >= 3

    asyncio.run(entity.async_will_remove_from_hass())
    assert not mqtt_manager._availability_callbacks
    assert not mqtt_manager._device_online_callbacks
