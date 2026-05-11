"""Diagnostics support for Bayrol integration."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import BAYROL_ACCESS_TOKEN, DOMAIN, INTERNAL_GUI_STATE_TOPICS

TO_REDACT = {BAYROL_ACCESS_TOKEN}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, config_entry: ConfigEntry) -> dict[str, object]:
    """Return diagnostics for a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id, {})
    mqtt_manager = entry_data.get("mqtt_manager")
    optional_controls = entry_data.get("optional_controls", {})
    latest_values = mqtt_manager.latest_topic_values if mqtt_manager else {}
    unregistered_values = mqtt_manager.unregistered_topic_values if mqtt_manager else {}

    return {
        "config_entry": async_redact_data(dict(config_entry.data), TO_REDACT),
        "config_entry_options": dict(config_entry.options),
        "mqtt_connected": mqtt_manager.is_connected if mqtt_manager else False,
        "subscriber_count": mqtt_manager.subscriber_count if mqtt_manager else 0,
        "subscribed_topics": sorted(mqtt_manager.subscribed_topics) if mqtt_manager else [],
        "optional_controls": optional_controls,
        "latest_topic_values": latest_values,
        "unregistered_topic_values": unregistered_values,
        "internal_gui_state_values": {topic: latest_values.get(topic) for topic in sorted(INTERNAL_GUI_STATE_TOPICS)},
    }
