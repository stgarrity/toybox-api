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


SENSOR_TYPES: tuple[ToyBoxSensorEntityDescription, ...] = (
    ToyBoxSensorEntityDescription(
        key="print_status",
        name="Print Status",
        icon="mdi:printer-3d",
        device_class=SensorDeviceClass.ENUM,
        options=["idle", "printing", "heating", "paused", "cancelling", "completed", "cancelled", "error", "unknown"],
        value_fn=lambda data: data.print_state.value,
        attributes_fn=lambda data: {
            "raw_state": data.current_request.state.value if data.current_request else None,
            "ui_state": data.printer.ui_state,
        },
    ),
    ToyBoxSensorEntityDescription(
        key="current_print_name",
        name="Current Print",
        icon="mdi:cube-outline",
        value_fn=lambda data: (
            data.current_request.print_name
            if data.current_request and data.current_request.is_active
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
            data.current_request.progress_percent
            if data.current_request and data.current_request.is_active
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
            data.current_request.remaining_seconds
            if data.current_request and data.current_request.is_active
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
            data.current_request.elapsed_seconds
            if data.current_request and data.current_request.is_active
            else None
        ),
    ),
    ToyBoxSensorEntityDescription(
        key="last_print_name",
        name="Last Print",
        icon="mdi:cube-send",
        value_fn=lambda data: (
            data.last_completed_request.print_name
            if data.last_completed_request
            else None
        ),
        attributes_fn=lambda data: (
            {
                "status": data.last_completed_request.simplified_state.value,
                "end_reason": data.last_completed_request.end_reason,
                "completed_at": (
                    data.last_completed_request.print_completion_time.isoformat()
                    if data.last_completed_request and data.last_completed_request.print_completion_time
                    else None
                ),
            }
            if data.last_completed_request
            else {}
        ),
    ),
    ToyBoxSensorEntityDescription(
        key="last_print_status",
        name="Last Print Status",
        icon="mdi:check-circle-outline",
        device_class=SensorDeviceClass.ENUM,
        options=["completed", "cancelled", "error", "unknown"],
        value_fn=lambda data: (
            data.last_completed_request.simplified_state.value
            if data.last_completed_request
            else None
        ),
    ),
    ToyBoxSensorEntityDescription(
        key="printer_model",
        name="Printer Model",
        icon="mdi:printer-3d-nozzle-heat-outline",
        value_fn=lambda data: data.printer.model,
        attributes_fn=lambda data: {
            "hardware_id": data.printer.hardware_id,
            "firmware": data.printer.firmware_version,
            "extruder": data.printer.extruder,
            "z_beam": data.printer.z_beam,
        },
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
            name=printer.display_name,
            manufacturer="ToyBox Labs",
            model=f"ToyBox ({printer.model})",
            sw_version=printer.firmware_version,
            hw_version=printer.hardware_id,
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
