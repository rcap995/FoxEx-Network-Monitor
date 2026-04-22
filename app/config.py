import os
import secrets

SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))
DATABASE_URL = "sqlite:///./data/foxex.db"
UPLOAD_DIR = "uploads/icons"
STATIC_ICONS_DIR = "static/icons"
DEFAULT_ICMP_INTERVAL = 60   # seconds
DEFAULT_SNMP_INTERVAL = 300  # seconds
DEFAULT_DNS_INTERVAL  = 300  # seconds
APP_TITLE = "FoxEx Network Monitor"
APP_VERSION = "0.3.0"

DEVICE_TYPES = [
    ("router",       "Router"),
    ("switch_l2",    "Switch Layer 2"),
    ("switch_l3",    "Switch Layer 3"),
    ("firewall",     "Firewall"),
    ("server",       "Server"),
    ("desktop",      "Desktop / PC"),
    ("laptop",       "Laptop"),
    ("access_point", "Access Point"),
    ("nas",          "NAS / Storage"),
    ("printer",      "Drucker"),
    ("camera",       "IP-Kamera"),
    ("vm",           "VM"),
    ("generic",      "Generisch"),
]
