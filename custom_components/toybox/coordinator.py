"""DataUpdateCoordinator for ToyBox 3D Printer."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from toybox_api import (
    ToyBoxClient,
    ToyBoxData,
    AuthenticationError,
    SessionExpiredError,
    ConnectionError as ToyBoxConnectionError,
    APIError,
)

from .const import ACTIVE_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class ToyBoxDataUpdateCoordinator(DataUpdateCoordinator[ToyBoxData]):
    """Manage fetching data from the ToyBox API."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: ToyBoxClient,
        entry: ConfigEntry,
    ) -> None:
        """Initialize coordinator."""
        self.client = client
        self.entry = entry

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> ToyBoxData:
        """Fetch data from the ToyBox API.

        Dynamically adjusts polling interval:
        - 30 seconds when a print is active
        - 5 minutes when idle
        """
        try:
            data = await self.client.get_all_data()

            # Dynamic polling: poll faster during active prints
            if data.is_printing:
                if self.update_interval != ACTIVE_SCAN_INTERVAL:
                    _LOGGER.debug("Print active — switching to 30s polling")
                    self.update_interval = ACTIVE_SCAN_INTERVAL
            else:
                if self.update_interval != DEFAULT_SCAN_INTERVAL:
                    _LOGGER.debug("No active print — switching to 5min polling")
                    self.update_interval = DEFAULT_SCAN_INTERVAL

            return data

        except (AuthenticationError, SessionExpiredError) as err:
            raise ConfigEntryAuthFailed(
                "Authentication failed — please re-enter credentials"
            ) from err

        except ToyBoxConnectionError as err:
            raise UpdateFailed(f"Cannot connect to make.toys: {err}") from err

        except APIError as err:
            raise UpdateFailed(f"API error: {err}") from err
