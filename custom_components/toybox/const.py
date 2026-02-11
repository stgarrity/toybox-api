"""Constants for the ToyBox integration."""
from datetime import timedelta

DOMAIN = "toybox"

# Config flow
CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# Polling intervals
DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)
ACTIVE_SCAN_INTERVAL = timedelta(seconds=30)

# Platforms
PLATFORMS = ["sensor", "binary_sensor"]
