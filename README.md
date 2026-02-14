# toybox-api — Python Client for ToyBox 3D Printers

Async Python client for [ToyBox 3D printers](https://www.toybox.com/) via the [make.toys](https://www.make.toys) Meteor DDP protocol.

Used by the [Home Assistant integration](https://github.com/sgarrity/homeassistant-toybox).

## Features

- Meteor DDP WebSocket client (no REST — make.toys is DDP-only)
- Authentication via Meteor accounts
- Real-time printer state via DDP subscriptions (`printerStates` collection)
- Print job tracking via `toyPrints` collection
- Time remaining / elapsed / progress calculations matching make.toys web app logic

## Installation

```bash
pip install toybox-api
```

## Usage

```python
import asyncio
from toybox_api import ToyBoxClient

async def main():
    async with ToyBoxClient() as client:
        await client.connect()
        await client.authenticate("email@example.com", "password")
        await client.subscribe_to_printer_data(["printer_id"])

        data = await client.get_all_data()
        print(f"Printer: {data.printer.display_name}")
        print(f"Online: {data.printer.is_online}")
        print(f"State: {data.print_state}")

        if data.current_request:
            print(f"Printing: {data.current_request.print_name}")
            print(f"Remaining: {data.current_request.remaining_seconds}s")

asyncio.run(main())
```

## Data Model

| Class | Source | Description |
|-------|--------|-------------|
| `PrinterStatus` | `printerStates` collection | Online state, model, hardware ID, firmware |
| `PrintRequest` | `toyPrints` collection | Active/completed prints with timing data |
| `ToyBoxData` | Coordinator container | Combines printer + current/last print request |

## Status

🟡 **Beta** — Implements real Meteor DDP protocol. Needs live testing with active prints.

## Project Structure

```
ha-toybox/
├── toybox_api/
│   ├── __init__.py
│   ├── client.py        # DDP WebSocket client
│   ├── models.py        # PrinterStatus, PrintRequest, ToyBoxData
│   ├── exceptions.py    # ToyBoxError hierarchy
│   └── const.py         # DDP URLs, subscription/method names
├── pyproject.toml
├── LICENSE
└── README.md
```

## License

MIT
