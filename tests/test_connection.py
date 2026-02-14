#!/usr/bin/env python3
"""Minimal connection test - no credentials needed."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from toybox_api.client import ToyBoxClient

async def main():
    client = ToyBoxClient()
    await client.connect()
    print("Connected:", client._connected)
    await client.close()

asyncio.run(main())
