"""ToyBox API client for make.toys using Meteor DDP protocol.

The make.toys platform is a Meteor app. All authenticated data flows through
DDP (Distributed Data Protocol) over WebSocket. This client implements the
DDP protocol directly using aiohttp's WebSocket support.

DDP message format:
- Connect: {"msg":"connect","version":"1","support":["1"]}
- Login: {"msg":"method","method":"login","params":[...]}
- Subscribe: {"msg":"sub","id":"<id>","name":"<sub>","params":[...]}
- Method call: {"msg":"method","method":"<name>","params":[...],"id":"<id>"}
- Data comes back as: {"msg":"added","collection":"...","id":"...","fields":{...}}
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import aiohttp

from .const import (
    DDP_URL,
    DDP_CONNECT_TIMEOUT,
    DEFAULT_TIMEOUT,
    METHOD_GET_PRINT_REQUESTS,
    SUB_MULTI_PRINTER_DATA,
    SUB_PRINTER_REQUESTS,
)
from .exceptions import (
    AuthenticationError,
    ConnectionError,
    APIError,
    SessionExpiredError,
)
from .models import PrinterStatus, PrintRequest, ToyBoxData, PrintState

_LOGGER = logging.getLogger(__name__)


class ToyBoxClient:
    """Async client for the ToyBox 3D printer API via Meteor DDP."""

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._owns_session = session is None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._msg_id = 0
        self._login_token: str | None = None
        self._user_id: str | None = None
        self._email: str | None = None
        self._password: str | None = None
        self._connected = False
        self._printer_ids: list[str] = []
        self._subscribed = False

        # DDP collections — populated by subscription messages
        self._collections: dict[str, dict[str, dict]] = {}
        # Pending responses for method calls
        self._pending: dict[str, asyncio.Future] = {}
        # Pending subscription ready signals
        self._pending_subs: dict[str, asyncio.Future] = {}
        # Background task for receiving DDP messages
        self._recv_task: asyncio.Task | None = None
        # Lock to prevent concurrent reconnection attempts
        self._reconnect_lock = asyncio.Lock()

    def _next_id(self) -> str:
        """Generate a unique message ID."""
        self._msg_id += 1
        return str(self._msg_id)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)
            )
            self._owns_session = True
        return self._session

    async def _send(self, msg: dict) -> None:
        """Send a DDP message over WebSocket."""
        if not self._ws or self._ws.closed:
            raise ConnectionError("WebSocket not connected")
        await self._ws.send_json(msg)

    async def _recv_loop(self) -> None:
        """Background task to receive and dispatch DDP messages."""
        if not self._ws:
            return
        try:
            async for ws_msg in self._ws:
                if ws_msg.type == aiohttp.WSMsgType.TEXT:
                    self._handle_message(ws_msg.data)
                elif ws_msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
        except Exception as err:
            _LOGGER.debug("DDP recv loop ended: %s", err)
        finally:
            self._connected = False

    def _handle_message(self, raw: str) -> None:
        """Handle an incoming DDP message."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("msg")

        if msg_type == "ping":
            # Respond to keep-alive pings
            asyncio.ensure_future(self._send({"msg": "pong"}))

        elif msg_type == "added":
            # Document added to a collection
            collection = msg.get("collection", "")
            doc_id = msg.get("id", "")
            fields = msg.get("fields", {})
            fields["_id"] = doc_id
            self._collections.setdefault(collection, {})[doc_id] = fields

        elif msg_type == "changed":
            # Document updated in a collection
            collection = msg.get("collection", "")
            doc_id = msg.get("id", "")
            fields = msg.get("fields", {})
            cleared = msg.get("cleared", [])
            if collection in self._collections and doc_id in self._collections[collection]:
                doc = self._collections[collection][doc_id]
                doc.update(fields)
                for key in cleared:
                    doc.pop(key, None)

        elif msg_type == "removed":
            # Document removed from a collection
            collection = msg.get("collection", "")
            doc_id = msg.get("id", "")
            if collection in self._collections:
                self._collections[collection].pop(doc_id, None)

        elif msg_type == "result":
            # Method call result
            msg_id = msg.get("id")
            if msg_id and msg_id in self._pending:
                future = self._pending.pop(msg_id)
                if "error" in msg:
                    future.set_exception(APIError(str(msg["error"])))
                else:
                    future.set_result(msg.get("result"))

        elif msg_type == "ready":
            # Subscription ready — resolve any pending futures
            for sub_id in msg.get("subs", []):
                if sub_id in self._pending_subs:
                    future = self._pending_subs.pop(sub_id)
                    if not future.done():
                        future.set_result(True)
            _LOGGER.debug("Subscriptions ready: %s", msg.get("subs"))

        elif msg_type == "connected":
            self._connected = True

    async def connect(self) -> None:
        """Establish DDP WebSocket connection."""
        session = await self._ensure_session()
        try:
            self._ws = await session.ws_connect(
                DDP_URL,
                timeout=DDP_CONNECT_TIMEOUT,
            )
        except aiohttp.ClientError as err:
            raise ConnectionError(f"Cannot connect to make.toys: {err}") from err

        # Start receive loop
        self._recv_task = asyncio.create_task(self._recv_loop())

        # Send DDP connect message
        await self._send({
            "msg": "connect",
            "version": "1",
            "support": ["1"],
        })

        # Wait for connected response
        for _ in range(50):  # 5 seconds max
            if self._connected:
                break
            await asyncio.sleep(0.1)
        else:
            raise ConnectionError("DDP connection handshake timed out")

    async def authenticate(self, email: str, password: str) -> bool:
        """Authenticate with make.toys via Meteor DDP login.

        Meteor's accounts-password package accepts login via email or username.
        We try email first, then fall back to username if that fails.

        Stores credentials for automatic reconnection.
        """
        if not self._connected:
            await self.connect()

        # Store for reconnection
        self._email = email
        self._password = password

        # Try email-style login first, then username-style
        login_attempts = [
            {"user": {"email": email}, "password": password},
            {"user": {"username": email}, "password": password},
        ]

        last_error = None
        for params in login_attempts:
            msg_id = self._next_id()
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            self._pending[msg_id] = future

            await self._send({
                "msg": "method",
                "method": "login",
                "id": msg_id,
                "params": [params],
            })

            try:
                result = await asyncio.wait_for(future, timeout=DEFAULT_TIMEOUT)
            except asyncio.TimeoutError:
                raise ConnectionError("Login timed out")
            except APIError as err:
                last_error = err
                if "User not found" in str(err):
                    continue  # Try next login style
                if "403" in str(err) or "Incorrect" in str(err):
                    raise AuthenticationError("Invalid email or password") from err
                raise

            if isinstance(result, dict) and result.get("token"):
                self._login_token = result.get("token")
                self._user_id = result.get("id")
                _LOGGER.debug("Authenticated as user %s", self._user_id)
                return True

        if last_error:
            raise AuthenticationError("Invalid email/username or password") from last_error
        raise AuthenticationError("Unexpected login response")

    async def _call_method(self, method: str, params: list | None = None) -> Any:
        """Call a Meteor DDP method and wait for the result."""
        if not self._connected:
            raise ConnectionError("Not connected")

        msg_id = self._next_id()
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future

        await self._send({
            "msg": "method",
            "method": method,
            "id": msg_id,
            "params": params or [],
        })

        try:
            return await asyncio.wait_for(future, timeout=DEFAULT_TIMEOUT)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise ConnectionError(f"Method {method} timed out")

    async def subscribe(self, name: str, params: list | None = None, wait: bool = False) -> str:
        """Subscribe to a Meteor publication.

        Args:
            name: Subscription name.
            params: Subscription parameters.
            wait: If True, block until the subscription signals "ready".
        """
        sub_id = self._next_id()

        if wait:
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            self._pending_subs[sub_id] = future

        await self._send({
            "msg": "sub",
            "id": sub_id,
            "name": name,
            "params": params or [],
        })

        if wait:
            try:
                await asyncio.wait_for(future, timeout=DEFAULT_TIMEOUT)
            except asyncio.TimeoutError:
                self._pending_subs.pop(sub_id, None)
                _LOGGER.warning("Subscription %s timed out waiting for ready", name)

        return sub_id

    async def setup(self) -> None:
        """Full setup: subscribe to user data, discover printers, subscribe to printer data.

        Call this after authenticate(). It handles the complete bootstrapping sequence
        that the make.toys web app performs on login:
        1. Subscribe to user-data-small (populates user profile with printer IDs)
        2. Extract printer IDs from user profile
        3. Subscribe to multi_printer_data and user_printer_requests_all_printers
        """
        # Step 1: Subscribe to user data and wait for it
        await self.subscribe("user-data-small", wait=True)

        # Step 2: Extract printer IDs from the user document
        self._printer_ids = self._extract_printer_ids()
        if not self._printer_ids:
            _LOGGER.warning("No printer IDs found for user %s", self._user_id)
            return

        _LOGGER.debug("Found printer IDs: %s", self._printer_ids)

        # Step 3: Subscribe to printer-specific data
        await self.subscribe_to_printer_data(self._printer_ids)
        self._subscribed = True

    def _extract_printer_ids(self) -> list[str]:
        """Extract printer IDs from the user profile in the users collection.

        The make.toys web app reads these from:
        - user.printers (array of {id: "..."} objects)
        - user.profile.printer_id (single printer fallback)
        """
        users = self._collections.get("users", {})
        user_data = users.get(self._user_id, {}) if self._user_id else {}

        if not user_data:
            # Try Meteor.users collection name variant
            users = self._collections.get("meteor_accounts_loginServiceConfiguration", {})
            user_data = users.get(self._user_id, {}) if self._user_id else {}

        printer_ids = []

        # Primary: user.printers array
        printers = user_data.get("printers", [])
        for p in printers:
            if isinstance(p, dict) and "id" in p:
                printer_ids.append(p["id"])
            elif isinstance(p, str):
                printer_ids.append(p)

        # Fallback: user.profile.printer_id
        if not printer_ids:
            profile = user_data.get("profile", {})
            if isinstance(profile, dict):
                pid = profile.get("printer_id")
                if pid:
                    printer_ids.append(pid)

        return printer_ids

    @property
    def printer_ids(self) -> list[str]:
        """Return discovered printer IDs."""
        return self._printer_ids

    async def subscribe_to_printer_data(self, printer_ids: list[str]) -> None:
        """Subscribe to printer state and print request data.

        This mirrors what the make.toys web app does in PrinterContext.tsx:
        - subscribe("multi_printer_data", printerArray)
        - subscribe("user_printer_requests_all_printers", printerArray)
        """
        printer_array = [{"id": pid} for pid in printer_ids]
        await self.subscribe(SUB_MULTI_PRINTER_DATA, [printer_array], wait=True)
        await self.subscribe(SUB_PRINTER_REQUESTS, [printer_array], wait=True)

    def get_printer_status(self, printer_id: str | None = None) -> PrinterStatus | None:
        """Get printer status from the local PrinterStates collection."""
        # Server uses "PrinterStates" (capital P/S)
        printers = self._collections.get("PrinterStates", {})
        if not printers:
            printers = self._collections.get("printerStates", {})
        if not printers:
            return None

        if printer_id:
            data = printers.get(printer_id)
            return PrinterStatus.from_dict(data) if data else None

        # Return the first printer found
        for data in printers.values():
            return PrinterStatus.from_dict(data)
        return None

    def get_print_requests(self, printer_id: str | None = None) -> list[PrintRequest]:
        """Get print requests from the local ToyPrints collection."""
        # Try multiple possible collection names
        requests = self._collections.get("toyPrints", {})
        if not requests:
            requests = self._collections.get("ToyPrints", {})
        if not requests:
            requests = self._collections.get("printRequests", {})
        result = []
        for data in requests.values():
            req = PrintRequest.from_dict(data)
            if printer_id and req.printer_id != printer_id:
                continue
            result.append(req)
        return result

    async def get_print_request_details(self, request_ids: list[str]) -> list[dict]:
        """Call getPrintRequestsByIds for detailed print request data."""
        if not request_ids:
            return []
        result = await self._call_method(
            METHOD_GET_PRINT_REQUESTS,
            [{"requestIds": request_ids}],
        )
        return result if isinstance(result, list) else []

    async def get_all_data(self) -> ToyBoxData:
        """Fetch all printer data from DDP collections.

        This reads from the locally-synced Meteor collections that are
        populated by our subscriptions. If the connection has dropped,
        it will attempt to reconnect.
        """
        # Reconnect if the WebSocket has dropped
        if not self._connected or (self._ws and self._ws.closed):
            await self._reconnect()

        # Get printer status
        printer = self.get_printer_status()
        if not printer:
            printer = PrinterStatus(
                printer_id="unknown",
                name="ToyBox",
                is_online=False,
            )

        # Get print requests for this printer
        requests = self.get_print_requests(printer.printer_id)

        # Find current active request and last completed
        current_request = None
        last_completed = None
        for req in requests:
            if req.is_active:
                current_request = req
            elif req.is_completed and (
                last_completed is None
                or (req.created_at and last_completed.created_at
                    and req.created_at > last_completed.created_at)
            ):
                last_completed = req

        # If we have a last_completed_print ID from the printer or user profile
        # but no matching request, try to fetch it via method call
        last_print_id = printer.last_completed_print
        if not last_print_id:
            # Check user profile for last_completed_print
            users = self._collections.get("users", {})
            user_data = users.get(self._user_id, {}) if self._user_id else {}
            profile = user_data.get("profile", {})
            if isinstance(profile, dict):
                last_print_id = profile.get("last_completed_print")

        if not last_completed and last_print_id:
            for req in requests:
                if req.id == last_print_id:
                    last_completed = req
                    break

            # If still not found, fetch via method call
            if not last_completed:
                try:
                    details = await self.get_print_request_details([last_print_id])
                    if details:
                        last_completed = PrintRequest.from_dict(details[0])
                except Exception:
                    _LOGGER.debug("Failed to fetch last completed print %s", last_print_id)

        return ToyBoxData(
            printer=printer,
            current_request=current_request,
            last_completed_request=last_completed,
        )

    async def _reconnect(self) -> None:
        """Reconnect to DDP, re-authenticate, and re-subscribe.

        Uses stored credentials from the initial authenticate() call.
        Protected by a lock to prevent concurrent reconnection attempts.
        """
        async with self._reconnect_lock:
            # Double-check after acquiring lock
            if self._connected and self._ws and not self._ws.closed:
                return

            _LOGGER.info("DDP connection lost — reconnecting")

            # Clean up old connection
            if self._recv_task and not self._recv_task.done():
                self._recv_task.cancel()
                try:
                    await self._recv_task
                except asyncio.CancelledError:
                    pass

            if self._ws and not self._ws.closed:
                await self._ws.close()

            self._connected = False
            self._subscribed = False
            self._collections.clear()

            # Reconnect
            try:
                await self.connect()

                # Re-authenticate (prefer token, fall back to password)
                if self._login_token:
                    try:
                        await self._login_with_token()
                    except (APIError, AuthenticationError):
                        _LOGGER.debug("Token login failed, trying password")
                        if self._email and self._password:
                            await self.authenticate(self._email, self._password)
                        else:
                            raise SessionExpiredError("Login token expired and no stored credentials")
                elif self._email and self._password:
                    await self.authenticate(self._email, self._password)
                else:
                    raise SessionExpiredError("No credentials available for reconnection")

                # Re-subscribe
                await self.setup()
                _LOGGER.info("DDP reconnected successfully")

            except Exception:
                _LOGGER.exception("DDP reconnection failed")
                raise

    async def _login_with_token(self) -> None:
        """Re-authenticate using a stored Meteor login token."""
        msg_id = self._next_id()
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future

        await self._send({
            "msg": "method",
            "method": "login",
            "id": msg_id,
            "params": [{"resume": self._login_token}],
        })

        try:
            result = await asyncio.wait_for(future, timeout=DEFAULT_TIMEOUT)
        except asyncio.TimeoutError:
            raise ConnectionError("Token login timed out")

        if isinstance(result, dict) and result.get("token"):
            self._login_token = result["token"]
            self._user_id = result.get("id", self._user_id)
        else:
            raise AuthenticationError("Token login failed")

    async def close(self) -> None:
        """Close the client."""
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass

        if self._ws and not self._ws.closed:
            await self._ws.close()

        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

        self._connected = False

    async def __aenter__(self) -> ToyBoxClient:
        """Enter async context."""
        await self._ensure_session()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Exit async context."""
        await self.close()
