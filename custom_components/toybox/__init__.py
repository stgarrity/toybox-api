"""ToyBox 3D Printer integration for Home Assistant."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from toybox_api import ToyBoxClient, ConnectionError as ToyBoxConnectionError, AuthenticationError

from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN
from .coordinator import ToyBoxDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ToyBox from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    client = ToyBoxClient()

    try:
        # Connect via DDP WebSocket and authenticate
        await client.connect()
        await client.authenticate(
            entry.data[CONF_EMAIL],
            entry.data[CONF_PASSWORD],
        )

        # Subscribe to printer data — the user's printer IDs come from
        # the user profile data pushed by the server after login.
        # We need to wait for the user-data-small subscription to populate,
        # then subscribe to printer-specific data.
        # For now, the subscription will auto-populate the collections.
        await client.subscribe("user-data-small")

    except ToyBoxConnectionError as err:
        await client.close()
        raise ConfigEntryNotReady(f"Cannot connect to make.toys: {err}") from err
    except AuthenticationError as err:
        await client.close()
        raise ConfigEntryNotReady(f"Authentication failed: {err}") from err

    coordinator = ToyBoxDataUpdateCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["client"].close()

    return unload_ok
