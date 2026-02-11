"""ToyBox API client for make.toys."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import BASE_URL, DEFAULT_TIMEOUT
from .exceptions import (
    AuthenticationError,
    ConnectionError,
    APIError,
    SessionExpiredError,
)
from .models import PrinterStatus, PrintJob, PrintState, ToyBoxData

_LOGGER = logging.getLogger(__name__)


class ToyBoxClient:
    """Async client for the ToyBox 3D printer API (make.toys).

    NOTE: This client uses stubbed endpoints. The make.toys platform is a
    Meteor app that communicates primarily via DDP (WebSocket). The actual
    API discovery requires capturing browser network traffic while logged in.

    Once we identify the real endpoints/methods, we'll update this client.
    The structure supports both REST-like endpoints and Meteor method calls.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._owns_session = session is None
        self._auth_token: str | None = None
        self._user_id: str | None = None
        self._base_url = BASE_URL

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)
            )
            self._owns_session = True
        return self._session

    async def authenticate(self, email: str, password: str) -> bool:
        """Authenticate with make.toys.

        Meteor apps typically authenticate via DDP 'login' method.
        Common approaches:
        1. DDP method call: {"msg":"method","method":"login","params":[...]}
        2. HTTP POST to accounts endpoint
        3. OAuth flow

        We attempt the HTTP approach first. If make.toys uses a different
        auth mechanism, this will need updating after API discovery.
        """
        session = await self._ensure_session()

        # Meteor apps often have a login endpoint at /api/v1/login
        # or handle auth via DDP. Try common patterns.
        login_payload = {
            "user": email,
            "password": password,
        }

        try:
            # Try Meteor-style REST login
            async with session.post(
                f"{self._base_url}/_api/v1/login",
                json=login_payload,
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    self._auth_token = data.get("data", {}).get("authToken", data.get("token"))
                    self._user_id = data.get("data", {}).get("userId", data.get("userId"))
                    _LOGGER.debug("Authenticated as user %s", self._user_id)
                    return True
                elif response.status in (401, 403):
                    raise AuthenticationError("Invalid email or password")
                else:
                    # The endpoint may not exist — this is expected until
                    # we discover the real auth mechanism
                    _LOGGER.warning(
                        "Login endpoint returned %s — may need API discovery",
                        response.status,
                    )
                    raise APIError(
                        f"Login failed with status {response.status}. "
                        "The API endpoints may need updating after browser "
                        "network traffic analysis."
                    )
        except aiohttp.ClientError as err:
            raise ConnectionError(f"Cannot connect to {self._base_url}: {err}") from err

    def _auth_headers(self) -> dict[str, str]:
        """Return auth headers for API requests."""
        headers: dict[str, str] = {}
        if self._auth_token:
            headers["X-Auth-Token"] = self._auth_token
        if self._user_id:
            headers["X-User-Id"] = self._user_id
        return headers

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        """Make an authenticated API request."""
        session = await self._ensure_session()
        url = f"{self._base_url}{path}"
        headers = {**self._auth_headers(), **kwargs.pop("headers", {})}

        try:
            async with session.request(method, url, headers=headers, **kwargs) as resp:
                if resp.status == 401:
                    raise SessionExpiredError("Session expired, re-authentication needed")
                if resp.status == 403:
                    raise AuthenticationError("Access denied")
                if resp.status >= 400:
                    text = await resp.text()
                    raise APIError(f"API error {resp.status}: {text}")
                return await resp.json()
        except aiohttp.ClientError as err:
            raise ConnectionError(f"Connection error: {err}") from err

    async def get_printer_status(self) -> PrinterStatus:
        """Fetch the current printer status.

        TODO: Replace with real endpoint after API discovery.
        Possible Meteor subscriptions: "printers", "myPrinters"
        Possible DDP methods: "getPrinterStatus", "getMyPrinter"
        """
        data = await self._request("GET", "/_api/v1/printer/status")
        return PrinterStatus.from_dict(data)

    async def get_print_jobs(self, limit: int = 10) -> list[PrintJob]:
        """Fetch recent print jobs.

        TODO: Replace with real endpoint after API discovery.
        Possible Meteor subscriptions: "printJobs", "myPrintHistory"
        Possible DDP methods: "getPrintJobs", "getRecentPrints"
        """
        data = await self._request(
            "GET", "/_api/v1/print-jobs", params={"limit": limit}
        )
        jobs_list = data if isinstance(data, list) else data.get("jobs", data.get("prints", []))
        return [PrintJob.from_dict(job) for job in jobs_list]

    async def get_current_job(self) -> PrintJob | None:
        """Fetch the currently active print job, if any.

        TODO: Replace with real endpoint after API discovery.
        """
        try:
            data = await self._request("GET", "/_api/v1/print-jobs/current")
            if not data or data.get("status") == "none":
                return None
            return PrintJob.from_dict(data)
        except APIError:
            return None

    async def get_all_data(self) -> ToyBoxData:
        """Fetch all printer data in a single coordinated call.

        This is what the DataUpdateCoordinator calls. It assembles
        all the data into a single ToyBoxData object.
        """
        # Fetch printer status
        try:
            printer = await self.get_printer_status()
        except (APIError, ConnectionError) as err:
            _LOGGER.debug("Could not fetch printer status: %s", err)
            # Return a default offline printer
            printer = PrinterStatus(
                printer_id="unknown",
                name="ToyBox",
                is_online=False,
                state=PrintState.UNKNOWN,
            )

        # Fetch print history
        try:
            jobs = await self.get_print_jobs(limit=5)
        except (APIError, ConnectionError) as err:
            _LOGGER.debug("Could not fetch print jobs: %s", err)
            jobs = []

        # Find the last completed job
        last_job = None
        for job in jobs:
            if job.state in (PrintState.COMPLETED, PrintState.CANCELLED, PrintState.ERROR):
                last_job = job
                break

        return ToyBoxData(
            printer=printer,
            last_job=last_job,
            print_history=jobs,
        )

    async def close(self) -> None:
        """Close the client session."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> ToyBoxClient:
        """Enter async context."""
        await self._ensure_session()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Exit async context."""
        await self.close()
