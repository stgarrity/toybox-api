"""Sensor platform for ToyBox 3D Printer."""
from __future__ import annotations

import sys
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from toybox_api import ToyBoxData

from .const import DOMAIN
from .coordinator import ToyBoxDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class ToyBoxSensorEntityDescription(SensorEntityDescription):
    """Describes a ToyBox sensor entity."""
    value_fn: Callable[[ToyBoxData], Any]
    attributes_fn: Callable[[ToyBoxData], dict[str, Any]] | None = None


def _format_duration(seconds: int | None) -> str | None:
    """Format seconds as H:MM:SS string."""
    if seconds is None:
        return None
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


SENSOR_TYPES: tuple[ToyBoxSensorEntityDescription, ...] = (
    ToyBoxSensorEntityDescription(
        key="print_status",
        name="Print Status",
        icon="mdi:printer-3d",
        device_class=SensorDeviceClass.ENUM,
        options=["idle", "printing", "completed", "paused", "cancelled", "error", "unknown"],
        value_fn=lambda data: data.printer.state.value,
    ),
    ToyBoxSensorEntityDescription(
        key="current_print_name",
        name="Current Print",
        icon="mdi:cube-outline",
        value_fn=lambda data: (
            data.printer.current_job.name
            if data.printer.current_job
            else None
        ),
    ),
    ToyBoxSensorEntityDescription(
        key="print_progress",
        name="Print Progress",
        icon="mdi:progress-check",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (
            data.printer.current_job.progress_percent
            if data.printer.current_job
            else None
        ),
    ),
    ToyBoxSensorEntityDescription(
        key="time_remaining",
        name="Time Remaining",
        icon="mdi:timer-sand",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda data: (
            data.printer.current_job.time_remaining_seconds
            if data.printer.current_job
            else None
        ),
    ),
    ToyBoxSensorEntityDescription(
        key="time_elapsed",
        name="Time Elapsed",
        icon="mdi:timer-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda data: (
            data.printer.current_job.time_elapsed_seconds
            if data.printer.current_job
            else None
        ),
    ),
    ToyBoxSensorEntityDescription(
        key="last_print_name",
        name="Last Print",
        icon="mdi:cube-send",
        value_fn=lambda data: (
            data.last_job.name if data.last_job else None
        ),
        attributes_fn=lambda data: (
            {
                "status": data.last_job.state.value,
                "completed_at": (
                    data.last_job.completed_at.isoformat()
                    if data.last_job and data.last_job.completed_at
                    else None
                ),
            }
            if data.last_job
            else {}
        ),
    ),
    ToyBoxSensorEntityDescription(
        key="last_print_status",
        name="Last Print Status",
        icon="mdi:check-circle-outline",
        device_class=SensorDeviceClass.ENUM,
        options=["completed", "failed", "cancelled", "unknown"],
        value_fn=lambda data: (
            data.last_job.state.value if data.last_job else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ToyBox sensors."""
    coordinator: ToyBoxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    async_add_entities(
        ToyBoxSensor(coordinator, description)
        for description in SENSOR_TYPES
    )


class ToyBoxSensor(
    CoordinatorEntity[ToyBoxDataUpdateCoordinator], SensorEntity
):
    """Representation of a ToyBox sensor."""

    entity_description: ToyBoxSensorEntityDescription

    def __init__(
        self,
        coordinator: ToyBoxDataUpdateCoordinator,
        description: ToyBoxSensorEntityDescription,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self.entity_description = description

        printer = coordinator.data.printer
        self._attr_unique_id = f"{printer.printer_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, printer.printer_id)},
            name=f"ToyBox {printer.name}",
            manufacturer="ToyBox Labs",
            model="ToyBox 3D Printer",
            sw_version=printer.firmware_version,
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        if self.entity_description.attributes_fn:
            return self.entity_description.attributes_fn(self.coordinator.data)
        return {}
