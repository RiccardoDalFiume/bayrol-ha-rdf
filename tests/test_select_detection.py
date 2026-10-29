"""Unit tests for Bayrol Smart&Easy optional controls detection."""

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

    if "homeassistant.components.sensor" not in sys.modules:
        sensor_module = ModuleType("homeassistant.components.sensor")

        class _DynamicEnum:
            def __getattr__(self, name):
                return name

        sensor_module.SensorDeviceClass = _DynamicEnum()
        sensor_module.SensorStateClass = _DynamicEnum()
        sys.modules["homeassistant.components.sensor"] = sensor_module

    if "homeassistant.components.select" not in sys.modules:
        select_module = ModuleType("homeassistant.components.select")
        select_module.SelectEntity = object
        sys.modules["homeassistant.components.select"] = select_module

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


_ensure_homeassistant_stubs()

from custom_components.bayrol.const import BAYROL_DEVICE_ID, SMART_EASY_DETECTOR_TOPICS  # noqa: E402
from custom_components.bayrol.mqtt_manager import BayrolMQTTManager  # noqa: E402
from custom_components.bayrol.select import _detect_smart_easy_optional_controls  # noqa: E402


def _build_manager():
    fake_hass = SimpleNamespace(loop=SimpleNamespace(call_soon_threadsafe=lambda cb, *args: cb(*args)))
    return BayrolMQTTManager(fake_hass, "device-123", "token-123")


def test_detection_removes_probe_callbacks():
    """Probe callbacks must not remain registered after detection."""
    manager = _build_manager()
    entity_values = []
    detector_topic = SMART_EASY_DETECTOR_TOPICS[0]
    manager.subscribe(detector_topic, entity_values.append)
    config_entry = SimpleNamespace(data={BAYROL_DEVICE_ID: "device-123"})

    asyncio.run(_detect_smart_easy_optional_controls(None, config_entry, manager, timeout_seconds=0.01))

    # Only the pre-existing callback is left, and it still receives values
    assert manager.subscriber_count == 1
    manager._on_message(
        None,
        None,
        SimpleNamespace(topic=f"d02/device-123/v/{detector_topic}", payload=b'{"v":"19.1"}'),
    )
    assert entity_values == ["19.1"]
