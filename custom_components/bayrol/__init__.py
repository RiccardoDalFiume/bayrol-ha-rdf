"""The Bayrol integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    BAYROL_ACCESS_TOKEN,
    BAYROL_DEVICE_ID,
    CONF_OPTIONAL_CONTROLS_POLICY,
    OPTIONAL_CONTROLS_POLICY_AUTO,
)
from .mqtt_manager import BayrolMQTTManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "select", "binary_sensor"]

# Max seconds to wait for the MQTT thread to exit on unload
MQTT_THREAD_JOIN_TIMEOUT = 1.0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bayrol from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Create and store MQTT manager
    mqtt_manager = BayrolMQTTManager(hass, entry.data[BAYROL_DEVICE_ID], entry.data[BAYROL_ACCESS_TOKEN])
    mqtt_manager.start()

    hass.data[DOMAIN][entry.entry_id] = {
        "mqtt_manager": mqtt_manager,
        "optional_controls": {
            "policy": entry.options.get(CONF_OPTIONAL_CONTROLS_POLICY, OPTIONAL_CONTROLS_POLICY_AUTO)
        },
    }

    # Reload the entry when options change so the new policy is applied
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Forward the setup to the platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry after an options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Clean up MQTT manager
        if entry.entry_id in hass.data[DOMAIN]:
            entry_data = hass.data[DOMAIN].pop(entry.entry_id)
            mqtt_manager = entry_data.get("mqtt_manager")
            if mqtt_manager:
                mqtt_manager.stop()
                if mqtt_manager.thread:
                    # join() blocks, so it must not run in the event loop
                    await hass.async_add_executor_job(mqtt_manager.thread.join, MQTT_THREAD_JOIN_TIMEOUT)

    return unload_ok
