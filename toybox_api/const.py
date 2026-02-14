"""Constants for the ToyBox API client."""

# Meteor DDP WebSocket endpoint
DDP_URL = "wss://www.make.toys/websocket"

# Meteor DDP subscriptions
SUB_MULTI_PRINTER_DATA = "multi_printer_data"
SUB_PRINTER_REQUESTS = "user_printer_requests_all_printers"
SUB_USER_DATA = "user-data-small"
SUB_PRINTER_QUEUES = "printerQueues"

# Meteor DDP methods
METHOD_GET_PRINT_REQUESTS = "getPrintRequestsByIds"
METHOD_GET_PRINTER_PROFILES = "getPrinterProfiles"
METHOD_CANCEL_PRINT = "requestCancelPrint"
METHOD_PAUSE_PRINT = "requestPausePrint"
METHOD_RESUME_PRINT = "requestResumePrint"

# Search API (public, no auth required)
SEARCH_API_URL = "https://search.make.toys"

# Timeouts
DEFAULT_TIMEOUT = 30  # seconds
DDP_CONNECT_TIMEOUT = 10  # seconds
DDP_PING_INTERVAL = 25  # seconds (keep-alive)
