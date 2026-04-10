"""DNS hostname resolution check."""
import socket
import time


def dns_check(url: str) -> dict:
    """Resolve the hostname of *url* to an IP address.
    Returns {resolved_ip, status ('online'|'offline'), response_ms}."""
    hostname = url.strip()
    for prefix in ("https://", "http://"):
        if hostname.lower().startswith(prefix):
            hostname = hostname[len(prefix):]
    hostname = hostname.split("/")[0].split(":")[0].strip()

    start = time.monotonic()
    try:
        ip = socket.gethostbyname(hostname)
        ms = round((time.monotonic() - start) * 1000, 2)
        return {"resolved_ip": ip, "status": "online", "response_ms": ms}
    except (socket.gaierror, socket.timeout, OSError):
        ms = round((time.monotonic() - start) * 1000, 2)
        return {"resolved_ip": "", "status": "offline", "response_ms": ms}
