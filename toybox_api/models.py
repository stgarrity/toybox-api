"""Data models for the ToyBox API."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from datetime import datetime


class PrintState(StrEnum):
    """State of the printer."""
    IDLE = "idle"
    PRINTING = "printing"
    COMPLETED = "completed"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class PrintJob:
    """Represents a print job."""
    id: str
    name: str
    state: PrintState
    progress_percent: float | None = None
    time_elapsed_seconds: int | None = None
    time_remaining_seconds: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict) -> PrintJob:
        """Create a PrintJob from API response data.

        NOTE: The field mappings here are placeholders. Once we capture
        actual API responses from make.toys, we'll update the keys to
        match the real data structure.
        """
        return cls(
            id=data.get("_id", data.get("id", "")),
            name=data.get("name", data.get("toyName", "Unknown")),
            state=_parse_state(data.get("status", data.get("state", "unknown"))),
            progress_percent=data.get("progress", data.get("percentComplete")),
            time_elapsed_seconds=data.get("timeElapsed", data.get("elapsedSeconds")),
            time_remaining_seconds=data.get("timeRemaining", data.get("remainingSeconds")),
            started_at=_parse_datetime(data.get("startedAt", data.get("createdAt"))),
            completed_at=_parse_datetime(data.get("completedAt", data.get("finishedAt"))),
        )


@dataclass
class PrinterStatus:
    """Represents the printer's current status."""
    printer_id: str
    name: str
    is_online: bool = False
    state: PrintState = PrintState.UNKNOWN
    current_job: PrintJob | None = None
    firmware_version: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> PrinterStatus:
        """Create PrinterStatus from API response data.

        NOTE: Field mappings are placeholders until we capture real API data.
        """
        current_job_data = data.get("currentJob", data.get("activeJob"))
        current_job = PrintJob.from_dict(current_job_data) if current_job_data else None

        return cls(
            printer_id=data.get("_id", data.get("id", "")),
            name=data.get("name", data.get("printerName", "ToyBox")),
            is_online=data.get("online", data.get("isOnline", False)),
            state=_parse_state(data.get("status", data.get("state", "unknown"))),
            current_job=current_job,
            firmware_version=data.get("firmwareVersion", data.get("firmware")),
        )


@dataclass
class ToyBoxData:
    """Container for all data from the ToyBox API.

    This is what the DataUpdateCoordinator returns.
    """
    printer: PrinterStatus
    last_job: PrintJob | None = None
    print_history: list[PrintJob] = field(default_factory=list)

    @property
    def is_printing(self) -> bool:
        """Return True if a print is currently active."""
        return self.printer.state == PrintState.PRINTING

    @property
    def active_job(self) -> PrintJob | None:
        """Return the active print job, if any."""
        if self.is_printing and self.printer.current_job:
            return self.printer.current_job
        return None


def _parse_state(raw: str | None) -> PrintState:
    """Parse a raw state string into a PrintState enum."""
    if not raw:
        return PrintState.UNKNOWN
    raw = raw.lower().strip()
    try:
        return PrintState(raw)
    except ValueError:
        # Map common variations
        mapping = {
            "complete": PrintState.COMPLETED,
            "done": PrintState.COMPLETED,
            "finished": PrintState.COMPLETED,
            "active": PrintState.PRINTING,
            "in_progress": PrintState.PRINTING,
            "inprogress": PrintState.PRINTING,
            "running": PrintState.PRINTING,
            "pause": PrintState.PAUSED,
            "cancel": PrintState.CANCELLED,
            "fail": PrintState.ERROR,
            "failed": PrintState.ERROR,
            "offline": PrintState.IDLE,
        }
        return mapping.get(raw, PrintState.UNKNOWN)


def _parse_datetime(raw: str | int | None) -> datetime | None:
    """Parse a datetime from API response (string or epoch)."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        # Epoch seconds or milliseconds
        if raw > 1e12:
            raw = raw / 1000  # milliseconds to seconds
        return datetime.fromtimestamp(raw)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
