"""Constants for the ToyBox API client."""

# Base URLs
BASE_URL = "https://www.make.toys"
WEBSOCKET_URL = "wss://www.make.toys/websocket"

# Meteor DDP endpoints (HTTP fallback)
LOGIN_URL = f"{BASE_URL}/api/v1/login"
PRINT_JOBS_URL = f"{BASE_URL}/api/v1/print-jobs"
PRINTER_STATUS_URL = f"{BASE_URL}/api/v1/printer/status"

# TODO: These endpoints are best-guesses. The actual Meteor app uses DDP
# over WebSocket. We need to capture browser network traffic to discover
# the real endpoints. Possible approaches:
# 1. Meteor methods called via DDP (e.g., "getPrintJobs", "getPrinterStatus")
# 2. REST-like endpoints if make.toys exposes any
# 3. Direct DDP subscription to collections like "printJobs", "printers"
#
# For now, the client is structured to make swapping in the real
# endpoints trivial once we reverse-engineer them.

# Timeouts
DEFAULT_TIMEOUT = 30  # seconds
