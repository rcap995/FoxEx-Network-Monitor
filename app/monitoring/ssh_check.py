"""SSH availability check — TCP banner grab, no credentials needed."""
import socket
import time
import re


def ssh_check(host: str, port: int = 22, timeout: int = 5) -> dict:
    """
    Connect to SSH port, read the server banner (SSH-2.0-...).
    Returns:
        {
            "reachable": bool,
            "connect_ms": float | None,
            "banner": str | None,   # e.g. "SSH-2.0-OpenSSH_8.9"
        }
    """
    t0 = time.monotonic()
    banner = None
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            connect_ms = round((time.monotonic() - t0) * 1000, 2)
            sock.settimeout(timeout)
            try:
                raw = sock.recv(256)
                banner = raw.decode("utf-8", errors="replace").strip()
                # Trim to just the banner line
                banner = banner.split("\n")[0].strip()
                # Validate it looks like an SSH banner
                if not re.match(r"SSH-\d+\.\d+", banner):
                    banner = None
            except (socket.timeout, OSError):
                pass
            return {"reachable": True, "connect_ms": connect_ms, "banner": banner}
    except (OSError, socket.timeout):
        return {"reachable": False, "connect_ms": None, "banner": None}
