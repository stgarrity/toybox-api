# ToyBox 3D Printer — Home Assistant Integration

Custom Home Assistant integration for the [ToyBox 3D Printer](https://www.toybox.com/) via the [make.toys](https://www.make.toys) platform.

## Features

- **Printer status** — idle, printing, completed, error
- **Current print name** — what's printing right now
- **Print progress** — percentage complete
- **Time remaining** — estimated time left on the current print
- **Time elapsed** — how long the current print has been running
- **Last print** — name and status of the most recent completed print
- **Printer online** — connectivity status
- **Printing active** — binary sensor for automations

### Dynamic Polling

- **5 minutes** when the printer is idle
- **30 seconds** when a print is actively running

## Installation

### HACS (Custom Repository)

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add: `https://github.com/sgarrity/ha-toybox`
3. Category: Integration
4. Install from HACS
5. Restart Home Assistant
6. Go to Settings → Devices & Services → Add Integration → "ToyBox 3D Printer"
7. Enter your make.toys email and password

### Manual Installation

1. Copy `custom_components/toybox/` to your Home Assistant `config/custom_components/` directory
2. Copy `toybox_api/` to your Home Assistant `config/custom_components/` directory (or install from PyPI when available)
3. Restart Home Assistant
4. Add the integration via Settings → Devices & Services

## Status

🟡 **Beta** — The API client implements the real Meteor DDP protocol (WebSocket) with proper authentication, subscriptions, and collection sync. Time remaining is calculated from `print_completion_time - now`, matching the make.toys web app logic. Needs live testing with an active print to verify the full flow.

## Development

The project follows the two-project pattern:

```
ha-toybox/
├── toybox_api/              # Standalone Python API client (Meteor DDP)
│   ├── __init__.py
│   ├── client.py            # DDP WebSocket client
│   ├── models.py            # Data models (matches Meteor schemas)
│   ├── exceptions.py        # Custom exceptions
│   └── const.py             # DDP URLs, subscription/method names
├── custom_components/
│   └── toybox/              # Home Assistant integration
│       ├── __init__.py      # Integration setup
│       ├── manifest.json    # HA metadata
│       ├── config_flow.py   # UI configuration
│       ├── coordinator.py   # Data polling with dynamic interval
│       ├── sensor.py        # Sensor entities
│       ├── binary_sensor.py # Binary sensor entities
│       ├── const.py         # Constants
│       └── translations/
│           └── en.json
├── hacs.json
├── LICENSE
└── README.md
```

## License

MIT
