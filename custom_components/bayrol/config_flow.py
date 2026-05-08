"""Config flow for Bayrol integration."""

from __future__ import annotations

import aiohttp
import json
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    BAYROL_ACCESS_TOKEN,
    BAYROL_APP_LINK_CODE,
    BAYROL_DEVICE_ID,
    BAYROL_DEVICE_TYPE,
    DOMAIN,
)


class BayrolConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bayrol."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            code = user_input[BAYROL_APP_LINK_CODE]
            # Fetch access token and device id from API
            url = f"https://www.bayrol-poolaccess.de/api/?code={code}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    data = await response.text()
                    data_json = json.loads(data)
                    access_token = data_json.get("accessToken")
                    device_id = data_json.get("deviceSerial")
                    if not access_token or not device_id:
                        errors["base"] = "invalid_response"
                    else:
                        return self.async_create_entry(
                            title="Bayrol",
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
                    vol.Required(BAYROL_DEVICE_TYPE): vol.In(["Automatic SALT", "Automatic Cl-pH", "PM5 Chlorine"]),
                }
            ),
            errors=errors,
        )
