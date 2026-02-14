#!/usr/bin/env python3
"""Live test of the ToyBox DDP client.

Usage:
    TOYBOX_EMAIL=stgarrity TOYBOX_PASSWORD=xxx python3 tests/test_live.py
"""
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logging.basicConfig(
    level=logging.DEBUG,
    stream=sys.stderr,
    format="%(levelname)s %(name)s: %(message)s",
)

from toybox_api.client import ToyBoxClient


async def test():
    email = os.environ.get("TOYBOX_EMAIL")
    password = os.environ.get("TOYBOX_PASSWORD")

    # Also try reading from .env file or creds file
    if not email or not password:
        for creds_path in [
            os.path.join(os.path.dirname(__file__), "..", ".env"),
            "/tmp/toybox_creds",
        ]:
            if os.path.exists(creds_path):
                with open(creds_path) as f:
                    content = f.read().strip()
                if "=" in content:
                    for line in content.split("\n"):
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            k, v = line.split("=", 1)
                            os.environ[k] = v
                else:
                    lines = content.split("\n")
                    if len(lines) >= 2:
                        os.environ["TOYBOX_EMAIL"] = lines[0].strip()
                        os.environ["TOYBOX_PASSWORD"] = lines[1].strip()
                email = os.environ.get("TOYBOX_EMAIL")
                password = os.environ.get("TOYBOX_PASSWORD")
                if email and password:
                    break

    if not email or not password:
        print("Set TOYBOX_EMAIL and TOYBOX_PASSWORD env vars or create .env file")
        sys.exit(1)

    client = ToyBoxClient()
    try:
        print("Connecting to DDP...")
        await client.connect()
        print("Connected ✓")

        print("Authenticating...")
        try:
            await client.authenticate(email, password)
        except Exception:
            # Retry with username-style login
            msg_id = client._next_id()
            future = asyncio.get_event_loop().create_future()
            client._pending[msg_id] = future
            await client._send(
                {
                    "msg": "method",
                    "method": "login",
                    "id": msg_id,
                    "params": [
                        {"user": {"username": email}, "password": password}
                    ],
                }
            )
            result = await asyncio.wait_for(future, timeout=15)
            client._login_token = result.get("token")
            client._user_id = result.get("id")

        print(f"Authenticated ✓ (user_id={client._user_id})")

        print("Running setup (discover printers, subscribe)...")
        await client.setup()
        print(f"Printer IDs: {client.printer_ids}")
        print(f"Collections: {list(client._collections.keys())}")
        for coll_name, docs in client._collections.items():
            print(f"  {coll_name}: {len(docs)} docs")

        data = await client.get_all_data()
        print(f"\n=== Printer ===")
        print(f"  Name: {data.printer.display_name}")
        print(f"  Model: {data.printer.model}")
        print(f"  Online: {data.printer.is_online}")
        print(f"  State: {data.print_state}")
        print(f"  Hardware ID: {data.printer.hardware_id}")
        print(f"  Firmware: {data.printer.firmware_version}")
        print(f"  Last Completed Print ID: {data.printer.last_completed_print}")

        if data.current_request:
            r = data.current_request
            print(f"\n=== Current Print ===")
            print(f"  Name: {r.print_name}")
            print(f"  State: {r.state}")
            print(f"  Remaining: {r.remaining_seconds}s")
            print(f"  Progress: {r.progress_percent}%")
        else:
            print("\n  No active print")

        if data.last_completed_request:
            r = data.last_completed_request
            print(f"\n=== Last Completed ===")
            print(f"  Name: {r.print_name}")
            print(f"  State: {r.state} (end_reason={r.end_reason})")
            if r.print_completion_time:
                print(f"  Completed at: {r.print_completion_time}")
        else:
            print("\n  No last completed in subscriptions")
            if data.printer.last_completed_print:
                print(
                    f"  Fetching via method call for ID={data.printer.last_completed_print}..."
                )
                details = await client.get_print_request_details(
                    [data.printer.last_completed_print]
                )
                for d in details:
                    apm = d.get("active_print_model", {})
                    print(f"  Name: {apm.get('name')}")
                    print(
                        f"  State: {d.get('state')} end_reason={d.get('end_reason')}"
                    )

        print(f"\n=== Raw printerStates ===")
        for doc_id, doc in client._collections.get("printerStates", {}).items():
            print(json.dumps(doc, indent=2, default=str)[:800])

        print(f"\n=== Raw toyPrints ===")
        for doc_id, doc in client._collections.get("toyPrints", {}).items():
            apm = doc.get("active_print_model", {})
            name = apm.get("name") if isinstance(apm, dict) else None
            print(
                f"  {doc_id}: state={doc.get('state')} "
                f"active={doc.get('is_active')} name={name}"
            )

        # Also dump raw users collection to see printer ID structure
        print(f"\n=== Raw users (printer fields only) ===")
        for doc_id, doc in client._collections.get("users", {}).items():
            filtered = {
                k: v
                for k, v in doc.items()
                if k in ("_id", "printers", "profile", "username", "emails")
            }
            print(json.dumps(filtered, indent=2, default=str)[:600])

    except Exception:
        import traceback

        traceback.print_exc()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(test())
