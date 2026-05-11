"""Config flow for Bayrol integration."""

from __future__ import annotations

import asyncio
import aiohttp
import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.core import callback

from .const import (
    BAYROL_ACCESS_TOKEN,
    BAYROL_APP_LINK_CODE,
    BAYROL_DEVICE_ID,
    BAYROL_DEVICE_TYPE,
    CONF_OPTIONAL_CONTROLS_POLICY,
    DOMAIN,
    OPTIONAL_CONTROLS_POLICY_AUTO,
    OPTIONAL_CONTROLS_POLICY_VALUES,
)

_LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT_SECONDS = 10
DEVICE_TYPES = ["Automatic SALT", "Automatic Cl-pH", "PM5 Chlorine"]


class BayrolConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bayrol."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Get options flow."""
        return BayrolOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            code = user_input[BAYROL_APP_LINK_CODE]
            access_token: str | None = None
            device_id: str | None = None
            # Fetch access token and device id from API
            url = f"https://www.bayrol-poolaccess.de/api/?code={code}"
            try:
                timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as response:
                        response.raise_for_status()
                        try:
                            data_json = await response.json(content_type=None)
                        except (json.JSONDecodeError, aiohttp.ContentTypeError):
                            errors["base"] = "invalid_response"
                        else:
                            access_token = data_json.get("accessToken")
                            device_id = data_json.get("deviceSerial")
                            if not access_token or not device_id:
                                errors["base"] = "invalid_response"
            except (aiohttp.ClientError, asyncio.TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:  # pragma: no cover - safety net
                _LOGGER.exception("Unexpected error while validating Bayrol link code")
                errors["base"] = "unknown"

            if access_token and device_id and not errors:
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Bayrol {device_id}",
                    data={
                        BAYROL_ACCESS_TOKEN: access_token,
                        BAYROL_DEVICE_ID: device_id,
                        BAYROL_DEVICE_TYPE: user_input[BAYROL_DEVICE_TYPE],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(BAYROL_APP_LINK_CODE): vol.All(str, vol.Length(min=8, max=8)),
                    vol.Required(BAYROL_DEVICE_TYPE): vol.In(DEVICE_TYPES),
                }
            ),
            errors=errors,
        )


class BayrolOptionsFlow(config_entries.OptionsFlow):
    """Handle Bayrol options flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_policy = self._config_entry.options.get(
            CONF_OPTIONAL_CONTROLS_POLICY,
            OPTIONAL_CONTROLS_POLICY_AUTO,
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_OPTIONAL_CONTROLS_POLICY, default=current_policy): vol.In(
                        OPTIONAL_CONTROLS_POLICY_VALUES
                    ),
                }
            ),
        )
