"""Unit tests for Bayrol MQTT manager callback API v2 behavior."""

from __future__ import annotations

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

from custom_components.bayrol.mqtt_manager import BayrolMQTTManager  # noqa: E402
import custom_components.bayrol.mqtt_manager as mqtt_manager  # noqa: E402


class _FakeClient:
    """Simple fake MQTT client used for unit tests."""

    last_kwargs = None

    def __init__(self, **kwargs):
        self.__class__.last_kwargs = kwargs
        self.subscribed = []
        self.published = []
        self.connected = True
        self.on_connect = None
        self.on_message = None
        self.on_disconnect = None

    def username_pw_set(self, *_args):
        return None

    def tls_set(self, **_kwargs):
        return None

    def tls_insecure_set(self, *_args):
        return None

    def connect(self, *_args):
        return None

    def loop_forever(self):
        return None

    def is_connected(self):
        return self.connected

    def subscribe(self, topic):
        self.subscribed.append(topic)
        return (0, 1)

    def publish(self, topic):
        self.published.append(topic)
        return (0, 1)


def _build_manager():
    fake_hass = SimpleNamespace(loop=SimpleNamespace(call_soon_threadsafe=lambda cb, *args: cb(*args)))
    return BayrolMQTTManager(fake_hass, "device-123", "token-123")


def test_start_configures_client_with_callback_api_v2(monkeypatch):
    """The MQTT client must be created using callback API VERSION2."""
    monkeypatch.setattr(mqtt_manager.paho, "Client", _FakeClient)
    manager = _build_manager()

    manager._start()

    assert _FakeClient.last_kwargs is not None
    assert _FakeClient.last_kwargs["callback_api_version"] == mqtt_manager.paho.CallbackAPIVersion.VERSION2
    assert manager.client.on_connect == manager._on_connect
    assert manager.client.on_disconnect == manager._on_disconnect


def test_on_connect_success_subscribes_and_requests_all_topics():
    """Successful connect must subscribe status + all registered topics."""
    manager = _build_manager()
    manager._subscribers["4.182"] = lambda _value: None
    fake_client = _FakeClient()

    manager._on_connect(fake_client, None, None, 0, None)

    assert f"d02/{manager.device_id}/v/1" in fake_client.subscribed
    assert f"d02/{manager.device_id}/v/4.182" in fake_client.subscribed
    assert f"d02/{manager.device_id}/g/4.182" in fake_client.published


def test_on_connect_failure_does_not_subscribe(caplog):
    """Failed connect should not subscribe to any topic."""
    manager = _build_manager()
    fake_client = _FakeClient()
    caplog.set_level("ERROR")

    manager._on_connect(fake_client, None, None, 7, None)

    assert fake_client.subscribed == []
    assert "Failed to connect to MQTT broker" in caplog.text


def test_on_disconnect_logs_reason_code(caplog):
    """Unexpected disconnect should log the MQTT v2 reason code."""
    manager = _build_manager()
    caplog.set_level("WARNING")

    manager._on_disconnect(None, None, None, 7, None)

    assert "Unexpected disconnection" in caplog.text
    assert "reason_code=7" in caplog.text


def test_topic_1_device_status_updates_device_online_state_and_callbacks():
    """Topic v/1 payload must update device online/offline state."""
    manager = _build_manager()
    updates = []
    manager.register_device_online_callback(updates.append)

    online_msg = SimpleNamespace(
        topic=f"d02/{manager.device_id}/v/1",
        payload=b'{"v":"17.4"}',
    )
    manager._on_message(None, None, online_msg)

    offline_msg = SimpleNamespace(
        topic=f"d02/{manager.device_id}/v/1",
        payload=b'{"v":"17.0"}',
    )
    manager._on_message(None, None, offline_msg)

    unknown_msg = SimpleNamespace(
        topic=f"d02/{manager.device_id}/v/1",
        payload=b'{"v":"17.9"}',
    )
    manager._on_message(None, None, unknown_msg)

    assert manager.device_online is False
    assert updates == [True, False]


def test_disconnect_marks_device_offline():
    """Disconnect should mark device state as offline."""
    manager = _build_manager()
    manager._set_device_online(True)

    manager._on_disconnect(None, None, None, 1, None)

    assert manager.device_online is False
