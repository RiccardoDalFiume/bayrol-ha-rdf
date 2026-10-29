"""Unit tests for Bayrol MQTT manager callback API v2 behavior."""

from __future__ import annotations

from types import ModuleType, SimpleNamespace
import sys
import time


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

    def disconnect(self):
        self.connected = False


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
    manager.subscribe("4.182", lambda _value: None)
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


def _message(manager, topic: str, value: str):
    return SimpleNamespace(topic=f"d02/{manager.device_id}/v/{topic}", payload=f'{{"v":"{value}"}}'.encode())


def test_on_connect_tolerates_topics_added_during_resubscribe():
    """Topics registered while on_connect iterates must not raise RuntimeError."""
    manager = _build_manager()
    manager.subscribe("4.1", lambda _value: None)
    manager.subscribe("4.2", lambda _value: None)

    class _ReentrantClient(_FakeClient):
        def subscribe(self, topic):
            # Simulate the HA loop registering a new topic mid-iteration
            if topic.endswith("/v/4.1"):
                manager.subscribe("4.99", lambda _value: None)
            return super().subscribe(topic)

    fake_client = _ReentrantClient()

    manager._on_connect(fake_client, None, None, 0, None)

    assert f"d02/{manager.device_id}/v/4.2" in fake_client.subscribed
    assert "4.99" in manager.subscribed_topics


def test_multiple_callbacks_on_same_topic_all_receive_value():
    """A second subscriber must not replace the first one."""
    manager = _build_manager()
    first, second = [], []
    manager.subscribe("4.182", first.append)
    manager.subscribe("4.182", second.append)

    manager._on_message(None, None, _message(manager, "4.182", "7.2"))

    assert first == ["7.2"]
    assert second == ["7.2"]
    assert manager.subscriber_count == 2


def test_unsubscribe_removes_only_that_callback():
    """The function returned by subscribe() must remove only its own callback."""
    manager = _build_manager()
    kept, removed = [], []
    manager.subscribe("4.182", kept.append)
    unsubscribe = manager.subscribe("4.182", removed.append)

    unsubscribe()
    manager._on_message(None, None, _message(manager, "4.182", "7.2"))

    assert kept == ["7.2"]
    assert removed == []


def test_unsubscribe_last_callback_marks_topic_unregistered():
    """Once a topic has no callbacks, its values are tracked as unregistered."""
    manager = _build_manager()
    unsubscribe = manager.subscribe("4.182", lambda _value: None)

    unsubscribe()
    manager._on_message(None, None, _message(manager, "4.182", "7.2"))

    assert "4.182" not in manager.subscribed_topics
    assert manager.unregistered_topic_values == {"4.182": "7.2"}


def test_subscribe_while_connected_subscribes_broker_once_per_topic():
    """Only the first callback for a topic subscribes on the broker; each one requests a value."""
    manager = _build_manager()
    manager.client = _FakeClient()

    manager.subscribe("4.182", lambda _value: None)
    manager.subscribe("4.182", lambda _value: None)

    assert manager.client.subscribed == [f"d02/{manager.device_id}/v/4.182"]
    assert manager.client.published == [f"d02/{manager.device_id}/g/4.182"] * 2


def test_stop_interrupts_reconnect_wait(monkeypatch):
    """stop() must end the reconnect loop without waiting the full reconnect period."""

    class _FailingClient(_FakeClient):
        def connect(self, *_args):
            raise OSError("broker unreachable")

    monkeypatch.setattr(mqtt_manager.paho, "Client", _FailingClient)
    monkeypatch.setattr(mqtt_manager, "RECONNECT_PERIOD", 30)
    manager = _build_manager()

    manager.start()
    time.sleep(0.05)  # let the thread reach the reconnect wait
    started = time.monotonic()
    manager.stop()
    manager.thread.join(timeout=2)

    assert not manager.thread.is_alive()
    assert time.monotonic() - started < 2
