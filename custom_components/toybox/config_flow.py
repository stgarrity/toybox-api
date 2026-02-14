"""Config flow for ToyBox 3D Printer integration."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

# Add parent path so we can import toybox_api from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass: HomeAssistant, data: dict) -> dict:
    """Validate the user input by attempting to authenticate."""
    from toybox_api import ToyBoxClient, AuthenticationError, ConnectionError

    client = ToyBoxClient()
    try:
        await client.connect()
        await client.authenticate(data[CONF_EMAIL], data[CONF_PASSWORD])
        return {"title": f"ToyBox ({data[CONF_EMAIL]})"}
    except AuthenticationError as err:
        raise InvalidAuth from err
    except ConnectionError as err:
        raise CannotConnect from err
    except Exception as err:
        _LOGGER.exception("Unexpected error during validation")
        raise CannotConnect from err
    finally:
        await client.close()


class ToyBoxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ToyBox."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Prevent duplicate configurations
                await self.async_set_unique_id(user_input[CONF_EMAIL])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=info["title"],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate invalid auth."""
