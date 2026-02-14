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
        self._connected = False

        # DDP collections — populated by subscription messages
        self._collections: dict[str, dict[str, dict]] = {}
        # Pending responses for method calls
        self._pending: dict[str, asyncio.Future] = {}
        # Background task for receiving DDP messages
        self._recv_task: asyncio.Task | None = None

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
            # Subscription ready
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

        Meteor's accounts-password package accepts login via:
        {"user": {"email": "..."}, "password": "..."}
        """
        if not self._connected:
            await self.connect()

        msg_id = self._next_id()
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future

        await self._send({
            "msg": "method",
            "method": "login",
            "id": msg_id,
            "params": [{
                "user": {"email": email},
                "password": password,
            }],
        })

        try:
            result = await asyncio.wait_for(future, timeout=DEFAULT_TIMEOUT)
        except asyncio.TimeoutError:
            raise ConnectionError("Login timed out")
        except APIError as err:
            if "403" in str(err) or "Incorrect" in str(err) or "User not found" in str(err):
                raise AuthenticationError("Invalid email or password") from err
            raise

        if isinstance(result, dict):
            self._login_token = result.get("token")
            self._user_id = result.get("id")
            _LOGGER.debug("Authenticated as user %s", self._user_id)
            return True

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

    async def subscribe(self, name: str, params: list | None = None) -> str:
        """Subscribe to a Meteor publication."""
        sub_id = self._next_id()
        await self._send({
            "msg": "sub",
            "id": sub_id,
            "name": name,
            "params": params or [],
        })
        return sub_id

    async def subscribe_to_printer_data(self, printer_ids: list[str]) -> None:
        """Subscribe to printer state and print request data.

        This mirrors what the make.toys web app does in PrinterContext.tsx:
        - subscribe("multi_printer_data", printerArray)
        - subscribe("user_printer_requests_all_printers", printerArray)
        """
        printer_array = [{"id": pid} for pid in printer_ids]
        await self.subscribe(SUB_MULTI_PRINTER_DATA, [printer_array])
        await self.subscribe(SUB_PRINTER_REQUESTS, [printer_array])

        # Give subscriptions a moment to populate collections
        await asyncio.sleep(1.5)

    def get_printer_status(self, printer_id: str | None = None) -> PrinterStatus | None:
        """Get printer status from the local PrinterStates collection."""
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
        requests = self._collections.get("toyPrints", {})
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
        populated by our subscriptions.
        """
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

        # If we have a last_completed_print ID from the printer but no
        # matching request, try to fetch it
        if not last_completed and printer.last_completed_print:
            for req in requests:
                if req.id == printer.last_completed_print:
                    last_completed = req
                    break

        return ToyBoxData(
            printer=printer,
            current_request=current_request,
            last_completed_request=last_completed,
        )

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
