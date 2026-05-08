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
import time
import threading
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
        self._subscribers = {}
        self._availability_callbacks = set()
        self._is_connected = False
        self._stop_event = threading.Event()
        # Generate a client ID matching the JS format: 'user_' + 8 hex chars
        self._client_id = "user_" + format(random.getrandbits(32), "08x")

    @property
    def is_connected(self) -> bool:
        """Return whether the MQTT client is currently connected."""
        return self._is_connected

    @property
    def subscribed_topics(self) -> set[str]:
        """Return registered topic identifiers."""
        return set(self._subscribers.keys())

    @property
    def subscriber_count(self) -> int:
        """Return number of registered subscribers."""
        return len(self._subscribers)

    def subscribe(self, topic: str, callback):
        """Subscribe to a topic with a callback."""
        self._subscribers[topic] = callback
        if self.client and self.client.is_connected():
            full_topic = f"d02/{self.device_id}/v/{topic}"
            self.client.subscribe(full_topic)
            _LOGGER.debug("Subscribed to %s", full_topic)
            # Request initial value (publish to 'g' kind)
            request_topic = f"d02/{self.device_id}/g/{topic}"
            self.client.publish(request_topic)
            _LOGGER.debug("Requested initial value via %s", request_topic)

    def register_availability_callback(self, callback) -> None:
        """Register a callback for MQTT availability changes."""
        self._availability_callbacks.add(callback)

    def unregister_availability_callback(self, callback) -> None:
        """Unregister a callback for MQTT availability changes."""
        self._availability_callbacks.discard(callback)

    def _set_connected(self, connected: bool) -> None:
        """Update connection status and notify listeners in HA loop."""
        if self._is_connected == connected:
            return

        self._is_connected = connected
        for callback in list(self._availability_callbacks):
            self.hass.loop.call_soon_threadsafe(callback, connected)

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
            # This mirrors JS processPendingRequests() behavior
            for topic in self._subscribers:
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

        if topic in self._subscribers:
            try:
                payload = msg.payload
                value = json.loads(payload)["v"]
                # Schedule the callback in the event loop
                self.hass.loop.call_soon_threadsafe(lambda: self._subscribers[topic](value))
            except Exception as e:
                _LOGGER.error("Invalid payload for %s: %s", msg.topic, e)
        else:
            _LOGGER.debug("Received message for unregistered topic: %s", msg.topic)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """Handle disconnection from the MQTT broker."""
        self._set_connected(False)
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
                    time.sleep(RECONNECT_PERIOD)
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
                time.sleep(RECONNECT_PERIOD)

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
