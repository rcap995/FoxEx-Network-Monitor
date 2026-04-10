"""TCP port check — tests if a TCP port is open and measures connection time."""
import socket
import time
from typing import Optional


def tcp_check(host: str, port: int, timeout: int = 5) -> dict:
    """
    Try to open a TCP connection to host:port.
    Returns:
        {
            "reachable":      bool,
            "connect_ms":     float | None,   # connection time in ms
            "port":           int,
        }
    """
    start = time.monotonic()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        elapsed = (time.monotonic() - start) * 1000
        sock.close()
        reachable = result == 0
        return {
            "reachable":  reachable,
            "connect_ms": round(elapsed, 2) if reachable else None,
            "port":       port,
        }
    except (socket.timeout, OSError):
        return {"reachable": False, "connect_ms": None, "port": port}
