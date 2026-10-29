"""MQTT Manager for Bayrol integration.

Aligned to the official Bayrol web client (DeviceDriver.js) behavior:
- Client ID: 'user_' + random hex (8 chars)
- Password: '*'
- TLS: self-signed cert (no verification)
- Reconnect period: 5 seconds
- Single wildcard subscription on connect, individual subscribe per object
"""

from __future__ import annotations

import logging
import random
import ssl
import threading
from collections.abc import Callable
import paho.mqtt.client as paho
import json

from homeassistant.core import HomeAssistant

from .const import (
    BAYROL_HOST,
    BAYROL_PORT,
)

_LOGGER = logging.getLogger(__name__)

# Reconnect period in seconds, matching the JS client's reconnectPeriod: 5000
RECONNECT_PERIOD = 5


class BayrolMQTTManager:
    """Manage the Bayrol MQTT connection."""

    def __init__(self, hass: HomeAssistant, device_id: str, mqtt_user: str):
        """Initialize the Bayrol MQTT manager."""
        self.hass = hass
        self.mqtt_user = mqtt_user
        self.device_id = device_id
        self.client = None
        self.thread = None
        self._subscribers: dict[str, list[Callable[[object], None]]] = {}
        self._availability_callbacks = set()
        self._device_online_callbacks: set[Callable[[bool | None], None]] = set()
        self._is_connected = False
        self._device_online: bool | None = None
        self._stop_event = threading.Event()
        self._latest_topic_values: dict[str, str] = {}
        self._unregistered_topic_values: dict[str, str] = {}
        # Generate a client ID matching the JS format: 'user_' + 8 hex chars
        self._client_id = "user_" + format(random.getrandbits(32), "08x")

    @property
    def is_connected(self) -> bool:
        """Return whether the MQTT client is currently connected."""
        return self._is_connected

    @property
    def device_online(self) -> bool | None:
        """Return whether the Bayrol device is currently online."""
        return self._device_online

    @property
    def subscribed_topics(self) -> set[str]:
        """Return registered topic identifiers."""
        return set(self._subscribers.keys())

    @property
    def subscriber_count(self) -> int:
        """Return number of registered subscribers."""
        return sum(len(callbacks) for callbacks in self._subscribers.values())

    @property
    def latest_topic_values(self) -> dict[str, str]:
        """Return latest known value for each received topic."""
        return dict(self._latest_topic_values)

    @property
    def unregistered_topic_values(self) -> dict[str, str]:
        """Return latest values received for topics without subscriber."""
        return dict(self._unregistered_topic_values)

    def subscribe(self, topic: str, callback: Callable[[object], None]) -> Callable[[], None]:
        """Add a callback for a topic and return a function that removes it.

        Several callbacks may share the same topic; each one receives every value.
        """
        callbacks = self._subscribers.get(topic)
        is_new_topic = callbacks is None
        # Replace the list instead of mutating it, so the MQTT thread never sees a partial update
        self._subscribers[topic] = [*(callbacks or []), callback]
        if self.client and self.client.is_connected():
            if is_new_topic:
                full_topic = f"d02/{self.device_id}/v/{topic}"
                self.client.subscribe(full_topic)
                _LOGGER.debug("Subscribed to %s", full_topic)
            # Request initial value (publish to 'g' kind) so the new callback gets data
            request_topic = f"d02/{self.device_id}/g/{topic}"
            self.client.publish(request_topic)
            _LOGGER.debug("Requested initial value via %s", request_topic)

        return lambda: self.unsubscribe(topic, callback)

    def unsubscribe(self, topic: str, callback: Callable[[object], None]) -> None:
        """Remove a callback for a topic.

        The broker subscription is kept: later values are tracked as unregistered.
        """
        callbacks = [cb for cb in self._subscribers.get(topic, []) if cb is not callback]
        if callbacks:
            self._subscribers[topic] = callbacks
        else:
            self._subscribers.pop(topic, None)

    def register_availability_callback(self, callback) -> None:
        """Register a callback for MQTT availability changes."""
        self._availability_callbacks.add(callback)

    def unregister_availability_callback(self, callback) -> None:
        """Unregister a callback for MQTT availability changes."""
        self._availability_callbacks.discard(callback)

    def register_device_online_callback(self, callback: Callable[[bool | None], None]) -> None:
        """Register a callback for Bayrol device online/offline changes."""
        self._device_online_callbacks.add(callback)

    def unregister_device_online_callback(self, callback: Callable[[bool | None], None]) -> None:
        """Unregister a callback for Bayrol device online/offline changes."""
        self._device_online_callbacks.discard(callback)

    def _set_connected(self, connected: bool) -> None:
        """Update connection status and notify listeners in HA loop."""
        if self._is_connected == connected:
            return

        self._is_connected = connected
        for callback in list(self._availability_callbacks):
            self.hass.loop.call_soon_threadsafe(callback, connected)

    def _set_device_online(self, device_online: bool | None) -> None:
        """Update device online state and notify listeners in HA loop."""
        if self._device_online == device_online:
            return

        self._device_online = device_online
        for callback in list(self._device_online_callbacks):
            self.hass.loop.call_soon_threadsafe(callback, device_online)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """Handle the connection to the MQTT broker."""
        if reason_code == 0:
            self._set_connected(True)
            _LOGGER.info("Connected to Bayrol MQTT broker (client_id=%s)", self._client_id)
            # Subscribe to device status topic first (like the JS client)
            status_topic = f"d02/{self.device_id}/v/1"
            client.subscribe(status_topic)
            _LOGGER.debug("Subscribed to device status: %s", status_topic)

            # Re-subscribe and request data for all registered topics
            # This mirrors JS processPendingRequests() behavior.
            # Iterate over a snapshot: the HA loop may add topics while this thread runs.
            for topic in list(self._subscribers):
                sub_topic = f"d02/{self.device_id}/v/{topic}"
                client.subscribe(sub_topic)
                req_topic = f"d02/{self.device_id}/g/{topic}"
                client.publish(req_topic)
                _LOGGER.debug("Re-subscribed to %s, requested via %s", sub_topic, req_topic)
        else:
            self._set_connected(False)
            _LOGGER.error(
                "Failed to connect to MQTT broker, reason code: %s",
                reason_code,
            )

    def _on_message(self, client, userdata, msg):
        """Handle the incoming messages from the MQTT broker."""
        _LOGGER.debug("Received message from topic: %s", msg.topic)

        # Parse topic: format is d02/{device_id}/v/{type}.{id}
        # Just get the last part of the topic
        topic_parts = msg.topic.split("/")
        topic = topic_parts[-1]

        try:
            payload = msg.payload.decode()
            value = json.loads(payload)["v"]
            value_str = str(value)
            self._latest_topic_values[topic] = value_str
        except Exception as e:
            _LOGGER.error("Invalid payload for %s: %s", msg.topic, e)
            return

        if topic == "1":
            if value_str == "17.4":
                self._set_device_online(True)
            elif value_str == "17.0":
                self._set_device_online(False)
            else:
                _LOGGER.debug("Unknown Bayrol device status value on topic 1: %s", value_str)

        callbacks = self._subscribers.get(topic)
        if callbacks:
            # Schedule the callbacks in the event loop
            for callback in callbacks:
                self.hass.loop.call_soon_threadsafe(callback, value)
        else:
            self._unregistered_topic_values[topic] = value_str
            _LOGGER.debug("Received message for unregistered topic: %s", msg.topic)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """Handle disconnection from the MQTT broker."""
        self._set_connected(False)
        self._set_device_online(False)
        if reason_code == 0:
            _LOGGER.info("Disconnected from Bayrol MQTT broker (clean)")
        else:
            _LOGGER.warning(
                "Unexpected disconnection from Bayrol MQTT broker (reason_code=%s). Will reconnect in %s seconds.",
                reason_code,
                RECONNECT_PERIOD,
            )

    def _start(self):
        """Start the MQTT manager with reconnect logic matching the JS client."""
        self.client = paho.Client(
            callback_api_version=paho.CallbackAPIVersion.VERSION2,
            client_id=self._client_id,
            transport="websockets",
        )
        # Password '*' as in the official JS client (not '1')
        self.client.username_pw_set(self.mqtt_user, "*")
        # TLS with no certificate verification (rejectUnauthorized: false in JS)
        self.client.tls_set(cert_reqs=ssl.CERT_NONE)
        self.client.tls_insecure_set(True)

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        # Use loop_start() + manual reconnect loop instead of loop_forever()
        # to respect the 5-second reconnect period like the JS client
        while not self._stop_event.is_set():
            try:
                _LOGGER.debug(
                    "Connecting to %s:%s as %s",
                    BAYROL_HOST,
                    BAYROL_PORT,
                    self._client_id,
                )
                self.client.connect(BAYROL_HOST, BAYROL_PORT, 60)
                self.client.loop_forever()
                if self._stop_event.is_set():
                    _LOGGER.debug("MQTT manager stop requested, exiting loop")
                    break
                if not self.client.is_connected():
                    _LOGGER.info("MQTT loop ended, waiting before reconnect...")
                    # wait() returns as soon as stop() is called, unlike time.sleep()
                    self._stop_event.wait(RECONNECT_PERIOD)
                else:
                    break
            except Exception as e:
                if self._stop_event.is_set():
                    break
                _LOGGER.error(
                    "MQTT connect() failed: %s. Retrying in %s seconds.",
                    e,
                    RECONNECT_PERIOD,
                )
                self._stop_event.wait(RECONNECT_PERIOD)

    def start(self):
        """Start the MQTT manager."""
        _LOGGER.debug("Starting MQTT manager (client_id=%s)", self._client_id)
        if not self.thread:
            self._stop_event.clear()
            self.thread = threading.Thread(target=self._start, daemon=True)
            self.thread.start()

    def stop(self):
        """Stop the MQTT manager thread and disconnect the client."""
        self._stop_event.set()
        if self.client:
            self.client.disconnect()

    def publish(self, topic: str, payload: str):
        """Publish an MQTT message through the managed client."""
        if not self.client or not self.client.is_connected():
            _LOGGER.warning("Cannot publish while MQTT is disconnected: topic=%s", topic)
            return None

        return self.client.publish(topic, payload)
