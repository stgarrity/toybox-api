#!/usr/bin/env python3
"""Dump raw DDP collection data for debugging."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from toybox_api.client import ToyBoxClient

async def main():
    # Read creds from file
    with open("/tmp/toybox_creds") as f:
        lines = f.read().strip().split("\n")
    email, password = lines[0], lines[1]

    client = ToyBoxClient()
    await client.connect()
    await client.authenticate(email, password)
    await client.setup()

    # Dump ALL collections raw
    for coll_name, docs in client._collections.items():
        print(f"\n{'='*60}")
        print(f"Collection: {coll_name} ({len(docs)} docs)")
        print(f"{'='*60}")
        for doc_id, doc in docs.items():
            print(json.dumps(doc, indent=2, default=str))

    # Also try the getPrintRequestsByIds method
    users = client._collections.get("users", {})
    for uid, udata in users.items():
        profile = udata.get("profile", {})
        last_print_id = profile.get("last_completed_print")
        if last_print_id:
            print(f"\n{'='*60}")
            print(f"Fetching print request: {last_print_id}")
            print(f"{'='*60}")
            result = await client._call_method(
                "getPrintRequestsByIds",
                [{"requestIds": [last_print_id]}],
            )
            print(json.dumps(result, indent=2, default=str))

    await client.close()

asyncio.run(main())
