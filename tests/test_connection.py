"""Real connection test to Bayrol servers.

These tests use credentials from the .env file to connect to real servers.
Behavior is exactly aligned to the official JS client (DeviceDriver.js):
- Client ID: 'user_' + 8 hex random chars
- Password: '*'
- TLS: rejectUnauthorized=false (self-signed cert)
- reconnectPeriod: 5000ms
- On connect: subscribe to device status topic first, then process pending
"""

import os
import random
import pytest
import aiohttp
import json
import logging
import asyncio
import ssl
import paho.mqtt.client as paho

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)

BAYROL_HOST = "www.bayrol-poolaccess.de"
BAYROL_PORT = 8083
RECONNECT_PERIOD = 5  # seconds, matching JS reconnectPeriod: 5000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_live_tests_enabled():
    """Skip live tests unless explicitly enabled by environment variable."""
    if os.getenv("BAYROL_RUN_LIVE_TESTS", "").lower() != "true":
        pytest.skip("Live MQTT tests are disabled. Set BAYROL_RUN_LIVE_TESTS=true to run them.")


async def _fetch_credentials():
    """Retrieve access_token and device_id from the API or .env."""
    access_token = os.getenv("BAYROL_ACCESS_TOKEN")
    device_id = os.getenv("BAYROL_DEVICE_ID")

    if access_token and device_id:
        return access_token, device_id

    app_link_code = os.getenv("BAYROL_APP_LINK_CODE")
    assert app_link_code, "You must set BAYROL_APP_LINK_CODE or BAYROL_ACCESS_TOKEN+BAYROL_DEVICE_ID in .env"

    _LOGGER.info("Fetching token from API for code: %s", app_link_code)
    url = f"https://{BAYROL_HOST}/api/?code={app_link_code}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            assert response.status == 200, f"API returned status {response.status}"
            data_json = json.loads(await response.text())

            access_token = data_json.get("accessToken")
            device_id = data_json.get("deviceSerial")

            assert access_token, f"accessToken missing in API response: {data_json}"
            assert device_id, f"deviceSerial missing in API response: {data_json}"
            _LOGGER.info("Token obtained! Device ID: %s", device_id)
            return access_token, device_id


def _create_mqtt_client(access_token: str, client_id: str | None = None):
    """Create a paho MQTT client configured identically to the JS official client.

    DeviceDriver.js I_Connect (line 1150-1209):
      - clientId: 'user_' + Math.random().toString(16).substr(2, 8)
      - username: device_token
      - password: '*'
      - reconnectPeriod: 5000
      - rejectUnauthorized: false  (self-signed cert)
      - transport: websockets (wss://...:8083/)
    """
    if client_id is None:
        client_id = "user_" + format(random.getrandbits(32), "08x")

    client = paho.Client(
        client_id=client_id,
        transport="websockets",
        callback_api_version=paho.CallbackAPIVersion.VERSION2,
    )
    # Password '*' — aligned with JS (not '1' as in the old plugin)
    client.username_pw_set(access_token, "*")
    # TLS without certificate verification — rejectUnauthorized: false
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.enable_logger(_LOGGER)

    return client, client_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_fetch_credentials():
    """Test that the registration API responds correctly."""
    _require_live_tests_enabled()
    app_link_code = os.getenv("BAYROL_APP_LINK_CODE")
    if not app_link_code:
        pytest.skip("BAYROL_APP_LINK_CODE not set in .env")

    url = f"https://{BAYROL_HOST}/api/?code={app_link_code}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            assert response.status == 200
            data_json = json.loads(await response.text())
            assert "accessToken" in data_json, f"Unexpected API response: {data_json}"
            assert "deviceSerial" in data_json, f"Unexpected API response: {data_json}"
            _LOGGER.info("API OK: device=%s", data_json["deviceSerial"])


@pytest.mark.asyncio
async def test_mqtt_connect_and_receive():
    """MQTT connection test aligned with the official JS client behavior.

    Flow replicated from DeviceDriver.js I_Connect:
    1. Create client with client_id 'user_XXXXXXXX', password '*', TLS insecure
    2. On connect: subscribe to device status topic (d02/{serial}/v/1)
    3. Wait for messages for 10 seconds
    4. Verify that at least 1 message has arrived (device status)
    """
    _require_live_tests_enabled()
    access_token, device_id = await _fetch_credentials()

    connected_event = asyncio.Event()
    messages_received = []

    client, client_id = _create_mqtt_client(access_token)

    def on_connect(client_obj, userdata, flags, reason_code, properties):
        _LOGGER.info("Connected! reason_code=%s, client_id=%s", reason_code, client_id)
        if reason_code == 0:
            # Step 1: Subscribe to device status (as in JS on 'connect')
            status_topic = f"d02/{device_id}/v/1"
            client_obj.subscribe(status_topic)
            _LOGGER.info("Subscribed to device status: %s", status_topic)
            connected_event.set()
        else:
            _LOGGER.error("Connection refused: %s", reason_code)

    def on_message(client_obj, userdata, msg):
        payload = msg.payload.decode()
        _LOGGER.info("Message: %s -> %s", msg.topic, payload)
        messages_received.append((msg.topic, payload))

    def on_disconnect(client_obj, userdata, disconnect_flags, reason_code, properties):
        _LOGGER.warning("Disconnected! reason_code=%s", reason_code)

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    _LOGGER.info("Connecting as %s to %s:%s ...", client_id, BAYROL_HOST, BAYROL_PORT)
    client.connect_async(BAYROL_HOST, BAYROL_PORT, 60)
    client.loop_start()

    try:
        await asyncio.wait_for(connected_event.wait(), timeout=15.0)
        assert connected_event.is_set(), "Connection failed (timeout)"

        _LOGGER.info("Connected! Waiting 10 seconds to observe messages...")
        await asyncio.sleep(10)

        _LOGGER.info("Messages received: %d", len(messages_received))
        for topic, payload in messages_received:
            _LOGGER.info("  -> %s = %s", topic, payload)

        assert len(messages_received) > 0, "No message received in 10 seconds"

    except asyncio.TimeoutError:
        pytest.fail("MQTT Connection: TIMEOUT after 15s")
    finally:
        client.loop_stop()
        client.disconnect()


@pytest.mark.asyncio
async def test_mqtt_subscribe_and_request_topic():
    """Test subscribe + request for a single topic (like registerObject in JS).

    DeviceDriver.js registerObject (line 916-956):
    1. Subscribe to topic: d02/{serial}/v/{type}.{id}
    2. Publish (request) to topic: d02/{serial}/g/{type}.{id}
    3. Wait for the value in the response
    """
    _require_live_tests_enabled()
    access_token, device_id = await _fetch_credentials()

    connected_event = asyncio.Event()
    topic_response = asyncio.Event()
    received_value = {}

    client, client_id = _create_mqtt_client(access_token)

    # Test topic: pH (4.182) — a numeric value that the device sends
    test_topic = "4.182"

    def on_connect(client_obj, userdata, flags, reason_code, properties):
        if reason_code == 0:
            _LOGGER.info("Connected as %s", client_id)
            connected_event.set()
        else:
            _LOGGER.error("Connection refused: %s", reason_code)

    def on_message(client_obj, userdata, msg):
        payload = msg.payload.decode()
        _LOGGER.info("Message: %s -> %s", msg.topic, payload)

        # Check if this is the response to our topic request
        if msg.topic.endswith(f"/v/{test_topic}"):
            try:
                data = json.loads(payload)
                received_value["v"] = data.get("v")
                received_value["raw"] = data
                topic_response.set()
            except json.JSONDecodeError as e:
                _LOGGER.error("JSON decode error: %s", e)

    def on_disconnect(client_obj, userdata, disconnect_flags, reason_code, properties):
        _LOGGER.warning("Disconnected! reason_code=%s", reason_code)

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    client.connect_async(BAYROL_HOST, BAYROL_PORT, 60)
    client.loop_start()

    try:
        await asyncio.wait_for(connected_event.wait(), timeout=15.0)

        # Step 1: Subscribe (like JS registerObject)
        sub_topic = f"d02/{device_id}/v/{test_topic}"
        client.subscribe(sub_topic)
        _LOGGER.info("Subscribed to %s", sub_topic)

        # Step 2: Request data (like JS registerObject publish to 'g')
        req_topic = f"d02/{device_id}/g/{test_topic}"
        client.publish(req_topic, "")
        _LOGGER.info("Requested data via %s", req_topic)

        # Step 3: Wait for response
        await asyncio.wait_for(topic_response.wait(), timeout=10.0)
        assert "v" in received_value, "No 'v' value in response"
        _LOGGER.info(
            "pH value received: %s (raw: %s)",
            received_value["v"],
            received_value["raw"],
        )

    except asyncio.TimeoutError:
        pytest.fail(f"Timeout waiting for response for topic {test_topic}")
    finally:
        client.loop_stop()
        client.disconnect()
