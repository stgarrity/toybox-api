"""Binary sensor platform for ToyBox 3D Printer."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from .const import DOMAIN
from .coordinator import ToyBoxDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ToyBox binary sensors."""
    coordinator: ToyBoxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    async_add_entities([
        ToyBoxOnlineSensor(coordinator),
        ToyBoxPrintingActiveSensor(coordinator),
    ])


def _device_info(coordinator: ToyBoxDataUpdateCoordinator) -> DeviceInfo:
    """Build DeviceInfo from coordinator data."""
    printer = coordinator.data.printer
    return DeviceInfo(
        identifiers={(DOMAIN, printer.printer_id)},
        name=printer.display_name,
        manufacturer="ToyBox Labs",
        model=f"ToyBox ({printer.model})",
        sw_version=printer.firmware_version,
        hw_version=printer.hardware_id,
    )


class ToyBoxOnlineSensor(
    CoordinatorEntity[ToyBoxDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor for printer online status."""

    def __init__(self, coordinator: ToyBoxDataUpdateCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        printer = coordinator.data.printer
        self._attr_unique_id = f"{printer.printer_id}_online"
        self._attr_name = f"{printer.display_name} Online"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = _device_info(coordinator)

    @property
    def is_on(self) -> bool:
        """Return True if printer is online."""
        return self.coordinator.data.printer.is_online


class ToyBoxPrintingActiveSensor(
    CoordinatorEntity[ToyBoxDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor for whether a print is actively running."""

    def __init__(self, coordinator: ToyBoxDataUpdateCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        printer = coordinator.data.printer
        self._attr_unique_id = f"{printer.printer_id}_printing"
        self._attr_name = f"{printer.display_name} Printing"
        self._attr_device_class = BinarySensorDeviceClass.RUNNING
        self._attr_icon = "mdi:printer-3d-nozzle"
        self._attr_device_info = _device_info(coordinator)

    @property
    def is_on(self) -> bool:
        """Return True if a print is actively running."""
        return self.coordinator.data.is_printing
