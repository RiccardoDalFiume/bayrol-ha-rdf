"""Unit tests for Bayrol config entry setup and unload."""

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


_ensure_homeassistant_stubs()

import custom_components.bayrol as bayrol  # noqa: E402
from custom_components.bayrol.const import (  # noqa: E402
    BAYROL_ACCESS_TOKEN,
    BAYROL_DEVICE_ID,
    CONF_OPTIONAL_CONTROLS_POLICY,
    DOMAIN,
)


class _FakeThread:
    def __init__(self):
        self.join_calls = []

    def join(self, timeout=None):
        self.join_calls.append(timeout)


class _FakeMQTTManager:
    def __init__(self, *_args):
        self.thread = _FakeThread()
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class _FakeConfigEntries:
    def __init__(self):
        self.forwarded = []
        self.reloaded = []

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded.append((entry.entry_id, platforms))

    async def async_unload_platforms(self, _entry, _platforms):
        return True

    async def async_reload(self, entry_id):
        self.reloaded.append(entry_id)


class _FakeHass:
    def __init__(self):
        self.data = {}
        self.config_entries = _FakeConfigEntries()
        self.executor_jobs = []

    async def async_add_executor_job(self, func, *args):
        self.executor_jobs.append((func, args))
        return func(*args)


def _build_entry():
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={BAYROL_DEVICE_ID: "device-123", BAYROL_ACCESS_TOKEN: "token-123"},
        options={CONF_OPTIONAL_CONTROLS_POLICY: "hide_all"},
        update_listeners=[],
        unload_callbacks=[],
    )

    def add_update_listener(listener):
        entry.update_listeners.append(listener)
        return lambda: entry.update_listeners.remove(listener)

    entry.add_update_listener = add_update_listener
    entry.async_on_unload = entry.unload_callbacks.append
    return entry


def test_setup_entry_registers_update_listener_that_reloads(monkeypatch):
    """Changing options must reload the entry so the new policy applies."""
    monkeypatch.setattr(bayrol, "BayrolMQTTManager", _FakeMQTTManager)
    hass = _FakeHass()
    entry = _build_entry()

    assert asyncio.run(bayrol.async_setup_entry(hass, entry)) is True
    assert len(entry.update_listeners) == 1
    assert len(entry.unload_callbacks) == 1
    assert hass.data[DOMAIN]["entry-1"]["optional_controls"] == {"policy": "hide_all"}

    asyncio.run(entry.update_listeners[0](hass, entry))

    assert hass.config_entries.reloaded == ["entry-1"]


def test_unload_entry_joins_mqtt_thread_in_executor(monkeypatch):
    """The blocking thread join must run in the executor, not in the event loop."""
    monkeypatch.setattr(bayrol, "BayrolMQTTManager", _FakeMQTTManager)
    hass = _FakeHass()
    entry = _build_entry()
    asyncio.run(bayrol.async_setup_entry(hass, entry))
    manager = hass.data[DOMAIN]["entry-1"]["mqtt_manager"]

    assert asyncio.run(bayrol.async_unload_entry(hass, entry)) is True

    assert manager.stopped
    assert hass.executor_jobs == [(manager.thread.join, (bayrol.MQTT_THREAD_JOIN_TIMEOUT,))]
    assert manager.thread.join_calls == [bayrol.MQTT_THREAD_JOIN_TIMEOUT]
    assert "entry-1" not in hass.data[DOMAIN]
