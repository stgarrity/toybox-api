"""Data models for the ToyBox API.

These models match the Meteor collections discovered from the make.toys
JavaScript bundle:
- PrinterStates (PrinterStateV2 schema)
- ToyPrints / PrintRequest schema
- PrintQueue / QueueEntry schemas
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from datetime import datetime, timezone


class PrinterModel(StrEnum):
    """Hardware model of the printer."""
    ESP32 = "esp32"
    ESP8266 = "esp8266"
    BRAVO = "bravo"
    ALPHA_3 = "alpha_3"
    CHARLIE = "charlie"


class UiState(StrEnum):
    """Printer UI state from PrinterStateV2 schema."""
    BUSY = "busy"
    NONE = "none"
    REQUEST_END = "request_end"
    INSERTING = "inserting"
    REQUEST_INSERT = "request_insert"
    REQUEST_REMOVE = "request_remove"
    REQUESTED = "requested"
    HEATING = "heating"
    READY = "ready"
    REMOVING = "removing"
    FAILED_PRINT = "failed_print"
    UNKNOWN = "unknown"


class PrintRequestState(StrEnum):
    """State of a print request (from PrinterHelpers analysis)."""
    REQUESTED = "requested"
    PREPARING = "preparing"
    HEATING_UP = "HeatingUp"
    PRINTING = "Printing"
    PAUSED = "paused"
    REQUESTED_PAUSE = "requested_pause"
    REQUESTED_RESUME = "requested_resume"
    REQUESTED_CANCEL = "requested_cancel"
    CANCELLED = "cancelled"
    DONE = "done"
    UNKNOWN = "unknown"


class PrintState(StrEnum):
    """Simplified print state for HA sensor display."""
    IDLE = "idle"
    PRINTING = "printing"
    HEATING = "heating"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class ActivePrintModel:
    """The model/toy currently being printed (blackbox object from API)."""
    id: str | None = None
    name: str | None = None
    image: str | None = None
    printing_time: int | None = None  # estimated total print time in ms
    is_user_upload: bool = False
    collection_type: str | None = None  # "user", "public", "toymodels", "pending"

    @classmethod
    def from_dict(cls, data: dict | None) -> ActivePrintModel | None:
        if not data:
            return None
        return cls(
            id=data.get("_id") or data.get("model_id"),
            name=data.get("name"),
            image=data.get("image"),
            printing_time=data.get("printing_time"),
            is_user_upload=data.get("isUserUpload", False),
            collection_type=data.get("collectionType"),
        )


@dataclass
class PrintRequest:
    """A print request from the ToyPrints collection.

    Matches the PrintRequest schema from userInteractionCollections.
    """
    id: str
    print_owner: str
    state: PrintRequestState
    is_active: bool = False
    printer_id: str | None = None
    active_print_model: ActivePrintModel | None = None
    print_start_time: datetime | None = None
    print_completion_time: datetime | None = None
    print_duration: int | None = None  # integer, milliseconds
    pause_start_time: datetime | None = None
    end_reason: str | None = None  # "completed", etc.
    error_code: int = 0
    pause_count: int = 0
    clean_name: str | None = None
    parent_toy_id: str | None = None
    is_hidden: bool = False
    created_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict) -> PrintRequest:
        return cls(
            id=data.get("_id", ""),
            print_owner=data.get("print_owner", ""),
            state=_parse_request_state(data.get("state")),
            is_active=data.get("is_active", False),
            printer_id=data.get("printer_id"),
            active_print_model=ActivePrintModel.from_dict(
                data.get("active_print_model")
            ),
            print_start_time=_parse_datetime(data.get("print_start_time")),
            print_completion_time=_parse_datetime(data.get("print_completion_time")),
            print_duration=data.get("print_duration"),
            pause_start_time=_parse_datetime(data.get("pause_start_time")),
            end_reason=data.get("end_reason"),
            error_code=data.get("error_code", 0),
            pause_count=data.get("pauseCount", 0),
            clean_name=data.get("clean_name"),
            parent_toy_id=data.get("parent_toy_id"),
            is_hidden=data.get("is_hidden", False),
            created_at=_parse_datetime(data.get("createdAt")),
        )

    @property
    def simplified_state(self) -> PrintState:
        """Map the raw request state to a simplified state for HA display."""
        match self.state:
            case PrintRequestState.PRINTING:
                return PrintState.PRINTING
            case PrintRequestState.HEATING_UP:
                return PrintState.HEATING
            case PrintRequestState.PAUSED | PrintRequestState.REQUESTED_PAUSE | PrintRequestState.REQUESTED_RESUME:
                return PrintState.PAUSED
            case PrintRequestState.REQUESTED_CANCEL:
                return PrintState.CANCELLING
            case PrintRequestState.CANCELLED:
                return PrintState.CANCELLED
            case PrintRequestState.DONE:
                if self.end_reason == "completed":
                    return PrintState.COMPLETED
                return PrintState.CANCELLED
            case PrintRequestState.REQUESTED | PrintRequestState.PREPARING:
                return PrintState.PRINTING  # about to print
            case _:
                return PrintState.UNKNOWN

    @property
    def is_cancelled(self) -> bool:
        return (
            self.state == PrintRequestState.CANCELLED
            or (self.state == PrintRequestState.DONE and self.end_reason != "completed")
        )

    @property
    def is_completed(self) -> bool:
        return self.state == PrintRequestState.DONE and self.end_reason == "completed"

    @property
    def is_paused(self) -> bool:
        return self.state in (
            PrintRequestState.PAUSED,
            PrintRequestState.REQUESTED_PAUSE,
        )

    @property
    def remaining_seconds(self) -> int | None:
        """Calculate remaining print time in seconds.

        Logic from make.toys countdownHooks.tsx:
        - Normal: print_completion_time - now
        - Paused: print_completion_time - pause_start_time (frozen countdown)
        """
        if not self.print_completion_time:
            return None

        if self.is_paused and self.pause_start_time:
            delta = self.print_completion_time - self.pause_start_time
        else:
            now = datetime.now(timezone.utc)
            completion = self.print_completion_time
            if completion.tzinfo is None:
                completion = completion.replace(tzinfo=timezone.utc)
            delta = completion - now

        seconds = int(delta.total_seconds())
        return max(0, seconds)

    @property
    def elapsed_seconds(self) -> int | None:
        """Calculate elapsed print time in seconds."""
        if not self.print_start_time:
            return None

        now = datetime.now(timezone.utc)
        start = self.print_start_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)

        if self.is_paused and self.pause_start_time:
            pause = self.pause_start_time
            if pause.tzinfo is None:
                pause = pause.replace(tzinfo=timezone.utc)
            return max(0, int((pause - start).total_seconds()))

        return max(0, int((now - start).total_seconds()))

    @property
    def total_seconds(self) -> int | None:
        """Total estimated print time in seconds."""
        if self.print_start_time and self.print_completion_time:
            start = self.print_start_time
            end = self.print_completion_time
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            return max(0, int((end - start).total_seconds()))
        return None

    @property
    def progress_percent(self) -> float | None:
        """Calculate progress as a percentage."""
        total = self.total_seconds
        elapsed = self.elapsed_seconds
        if total and total > 0 and elapsed is not None:
            return min(100.0, round((elapsed / total) * 100, 1))
        return None

    @property
    def print_name(self) -> str | None:
        """Get the display name of the print."""
        if self.active_print_model and self.active_print_model.name:
            return self.active_print_model.name
        return self.clean_name


@dataclass
class PrinterStatus:
    """Represents a printer from the PrinterStates collection.

    Matches the PrinterStateV2 schema from printerCollections.ts.
    """
    printer_id: str
    name: str = "ToyBox"
    model: str = "esp32"
    is_online: bool = False
    ui_state: str = "none"
    hardware_id: str | None = None
    firmware_version: str | None = None
    extruder: str | None = None  # PLA, TPU, Unknown, none
    z_beam: str | None = None  # standard, tall, none, Unknown
    last_ping: datetime | None = None
    last_completed_print: str | None = None
    calibration_value: int | None = None
    owners: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> PrinterStatus:
        return cls(
            printer_id=data.get("_id", ""),
            name=data.get("name", "ToyBox"),
            model=data.get("model", "esp32"),
            is_online=data.get("online", False),
            ui_state=data.get("ui_state", "none"),
            hardware_id=data.get("hardware_id"),
            firmware_version=data.get("version") or data.get("spversion"),
            extruder=data.get("extruder"),
            z_beam=data.get("zBeam"),
            last_ping=_parse_datetime(data.get("last_ping")),
            last_completed_print=data.get("last_completed_print"),
            calibration_value=data.get("calibrationValue"),
            owners=data.get("owners", []),
        )

    @property
    def display_name(self) -> str:
        """Friendly display name matching make.toys logic."""
        prefix = "Comet" if self.model == "bravo" else "ToyBox"
        if self.hardware_id and self.hardware_id.lower() != "pending":
            return f"{prefix} ({self.hardware_id[-6:]})"
        return prefix


@dataclass
class ToyBoxData:
    """Container for all data from the ToyBox API.

    This is what the DataUpdateCoordinator returns.
    """
    printer: PrinterStatus
    current_request: PrintRequest | None = None
    last_completed_request: PrintRequest | None = None

    @property
    def is_printing(self) -> bool:
        """Return True if a print is actively running."""
        if self.current_request and self.current_request.is_active:
            return self.current_request.state in (
                PrintRequestState.PRINTING,
                PrintRequestState.HEATING_UP,
                PrintRequestState.REQUESTED,
                PrintRequestState.PREPARING,
            )
        return False

    @property
    def is_busy(self) -> bool:
        """Return True if printer is doing anything (printing, pausing, etc)."""
        return self.current_request is not None and self.current_request.is_active

    @property
    def print_state(self) -> PrintState:
        """Get the simplified print state."""
        if self.current_request and self.current_request.is_active:
            return self.current_request.simplified_state
        return PrintState.IDLE


def _parse_request_state(raw: str | None) -> PrintRequestState:
    """Parse a raw state string into a PrintRequestState."""
    if not raw:
        return PrintRequestState.UNKNOWN
    try:
        return PrintRequestState(raw)
    except ValueError:
        return PrintRequestState.UNKNOWN


def _parse_datetime(raw) -> datetime | None:
    """Parse a datetime from Meteor (can be Date object, ISO string, or epoch)."""
    if raw is None:
        return None
    # Meteor sends dates as {"$date": epoch_ms} in DDP, or as Date objects
    if isinstance(raw, dict) and "$date" in raw:
        raw = raw["$date"]
    if isinstance(raw, (int, float)):
        if raw > 1e12:
            raw = raw / 1000  # milliseconds to seconds
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(raw, datetime):
        return raw
    return None
