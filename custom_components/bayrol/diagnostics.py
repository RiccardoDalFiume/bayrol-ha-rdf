"""Diagnostics support for Bayrol integration."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import BAYROL_ACCESS_TOKEN, DOMAIN

TO_REDACT = {BAYROL_ACCESS_TOKEN}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, config_entry: ConfigEntry) -> dict[str, object]:
    """Return diagnostics for a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id, {})
    mqtt_manager = entry_data.get("mqtt_manager")

    return {
        "config_entry": async_redact_data(dict(config_entry.data), TO_REDACT),
        "mqtt_connected": mqtt_manager.is_connected if mqtt_manager else False,
        "subscriber_count": mqtt_manager.subscriber_count if mqtt_manager else 0,
        "subscribed_topics": sorted(mqtt_manager.subscribed_topics) if mqtt_manager else [],
    }
