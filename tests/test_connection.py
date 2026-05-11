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
import re
import json
import logging
import asyncio
import ssl
from pathlib import Path

import aiohttp
import paho.mqtt.client as paho
import pytest

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)

BAYROL_HOST = "www.bayrol-poolaccess.de"
BAYROL_PORT = 8083
RECONNECT_PERIOD = 5  # seconds, matching JS reconnectPeriod: 5000
SMART_EASY_OPTIONAL_CONTROL_TOPICS = {"5.184", "5.186", "5.187", "5.188", "5.189"}
SMART_EASY_DETECTOR_TOPICS = {"5.257", "5.265", "5.266"}
INTERNAL_GUI_STATE_TOPICS = {"5.76", "5.79"}


def _extract_dict_block(text: str, marker: str) -> str:
    """Extract python dict block body from marker assignment."""
    match = re.search(rf"{marker}\s*=\s*\{{", text)
    if not match:
        return ""

    depth = 1
    idx = match.end()
    start = idx
    while idx < len(text) and depth > 0:
        if text[idx] == "{":
            depth += 1
        elif text[idx] == "}":
            depth -= 1
        idx += 1

    return text[start : idx - 1]


def _parse_select_topics(block: str) -> dict[str, dict[str, object]]:
    """Parse select topic metadata from a constants block."""
    topics: dict[str, dict[str, object]] = {}
    topic_pattern = re.compile(r'"([0-9]+\.[0-9]+)"\s*:\s*\{')
    idx = 0
    while True:
        topic_match = topic_pattern.search(block, idx)
        if not topic_match:
            break
        topic = topic_match.group(1)
        obj_start = topic_match.end() - 1
        cursor = obj_start + 1
        depth = 1
        while cursor < len(block) and depth > 0:
            if block[cursor] == "{":
                depth += 1
            elif block[cursor] == "}":
                depth -= 1
            cursor += 1
        obj_text = block[obj_start:cursor]
        idx = cursor

        if '"entity_type": "select"' not in obj_text:
            continue

        coefficient = None
        coefficient_match = re.search(r'"coefficient"\s*:\s*([^,\n]+)', obj_text)
        if coefficient_match:
            raw = coefficient_match.group(1).strip()
            if raw not in {"None", "null"}:
                try:
                    coefficient = float(raw)
                except ValueError:
                    coefficient = None

        options: list[str] = []
        options_match = re.search(r'"options"\s*:\s*\[(.*?)\]', obj_text, flags=re.S)
        if options_match:
            for line in options_match.group(1).splitlines():
                line = line.split("#")[0].strip().rstrip(",")
                if not line:
                    continue
                if line.startswith('"') and line.endswith('"'):
                    options.append(line[1:-1])
                else:
                    options.append(str(float(line) if "." in line else int(line)))

        name_match = re.search(r'"name"\s*:\s*"([^"]+)"', obj_text)
        topics[topic] = {
            "name": name_match.group(1) if name_match else topic,
            "options": options,
            "coefficient": coefficient,
        }

    return topics


def _parse_all_topics(block: str) -> set[str]:
    """Parse all topic keys from a constants block."""
    return set(re.findall(r'"([0-9]+\.[0-9]+)"\s*:\s*\{', block))


def _parse_automatic_mapping(text: str) -> dict[str, str]:
    """Parse AUTOMATIC_MQTT_TO_TEXT_MAPPING from const.py text."""
    block = _extract_dict_block(text, "AUTOMATIC_MQTT_TO_TEXT_MAPPING")
    mapping = {}
    for key, value in re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', block):
        mapping[key] = value
    return mapping


def _load_automatic_salt_inventory() -> tuple[list[str], dict[str, dict[str, object]], dict[str, str]]:
    """Load Automatic SALT topic inventory from const.py without importing HA modules."""
    const_path = Path(__file__).resolve().parents[1] / "custom_components" / "bayrol" / "const.py"
    text = const_path.read_text(encoding="utf-8")
    automatic_block = _extract_dict_block(text, "SENSOR_TYPES_AUTOMATIC")
    automatic_salt_block = _extract_dict_block(text, "SENSOR_TYPES_AUTOMATIC_SALT")
    automatic_topics = _parse_select_topics(automatic_block)
    automatic_salt_topics = _parse_select_topics(automatic_salt_block)
    merged_select_topics = {**automatic_topics, **automatic_salt_topics}
    all_known_topics = sorted(_parse_all_topics(automatic_block) | _parse_all_topics(automatic_salt_block))
    return all_known_topics, merged_select_topics, _parse_automatic_mapping(text)


def _resolve_select_value(raw_value: str, topic_meta: dict[str, object], mapping: dict[str, str]) -> str:
    """Resolve raw MQTT value to option text as select.py does."""
    options = [str(option) for option in topic_meta.get("options", [])]
    display_options = [mapping.get(option, option) for option in options]

    if raw_value in mapping:
        return mapping[raw_value]

    coefficient = topic_meta.get("coefficient")
    if coefficient not in (None, -1) and options:
        try:
            converted = float(raw_value) / float(coefficient)
            option_floats = [float(option) for option in options]
            nearest = min(option_floats, key=lambda candidate: abs(candidate - converted))
            candidate = str(nearest)
            if candidate in display_options:
                return candidate
        except ValueError:
            return raw_value

    return raw_value


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


@pytest.mark.asyncio
async def test_mqtt_live_audit_automatic_salt_topics():
    """Audit Automatic SALT topic coverage and mapping against live broker values."""
    _require_live_tests_enabled()
    access_token, device_id = await _fetch_credentials()
    known_topics, select_topics, automatic_mapping = _load_automatic_salt_inventory()
    capture_seconds = int(os.getenv("BAYROL_AUDIT_DURATION_SECONDS", "45"))

    connected_event = asyncio.Event()
    received_by_topic: dict[str, set[str]] = {}

    client, client_id = _create_mqtt_client(access_token)

    def on_connect(client_obj, userdata, flags, reason_code, properties):
        _LOGGER.info("Connected for audit as %s (reason_code=%s)", client_id, reason_code)
        if reason_code != 0:
            return
        client_obj.subscribe(f"d02/{device_id}/v/#")
        for topic in known_topics:
            client_obj.publish(f"d02/{device_id}/g/{topic}", "")
        connected_event.set()

    def on_message(client_obj, userdata, msg):
        topic = msg.topic.split("/")[-1]
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            return
        value = payload.get("v")
        if value is None:
            return
        received_by_topic.setdefault(topic, set()).add(str(value))

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(BAYROL_HOST, BAYROL_PORT, 60)
    client.loop_start()

    try:
        await asyncio.wait_for(connected_event.wait(), timeout=15.0)
        await asyncio.sleep(capture_seconds)
    finally:
        client.loop_stop()
        client.disconnect()

    covered_select_topics = sorted(topic for topic in select_topics if topic in received_by_topic)
    uncovered_select_topics = sorted(topic for topic in select_topics if topic not in received_by_topic)
    unknown_topics = sorted(topic for topic in received_by_topic if topic not in known_topics)

    unmapped_values = []
    for topic, topic_meta in sorted(select_topics.items()):
        observed = sorted(received_by_topic.get(topic, set()))
        if not observed:
            continue
        display_options = [automatic_mapping.get(option, option) for option in topic_meta.get("options", [])]
        for raw_value in observed:
            resolved = _resolve_select_value(raw_value, topic_meta, automatic_mapping)
            if resolved not in display_options:
                unmapped_values.append(
                    {
                        "topic": topic,
                        "name": topic_meta.get("name"),
                        "value": raw_value,
                        "resolved": resolved,
                    }
                )

    report = {
        "device_id": device_id,
        "capture_seconds": capture_seconds,
        "known_topics_total": len(known_topics),
        "observed_topics_total": len(received_by_topic),
        "covered_select_topics": covered_select_topics,
        "uncovered_select_topics": uncovered_select_topics,
        "unknown_topics": unknown_topics,
        "unknown_topics_internal_gui_subset": sorted(
            topic for topic in unknown_topics if topic in INTERNAL_GUI_STATE_TOPICS
        ),
        "smart_easy_topics_seen": sorted(
            topic
            for topic in received_by_topic
            if topic in SMART_EASY_OPTIONAL_CONTROL_TOPICS or topic in SMART_EASY_DETECTOR_TOPICS
        ),
        "unmapped_select_values": unmapped_values,
    }
    _LOGGER.info("Automatic SALT live audit report:\n%s", json.dumps(report, indent=2))

    assert received_by_topic, "Live audit did not receive any MQTT value"
