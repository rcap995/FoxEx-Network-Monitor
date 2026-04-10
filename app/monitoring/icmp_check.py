"""ICMP monitoring via system ping command (no root required)."""
import subprocess
import platform
import re
from typing import Optional


def ping(host: str, count: int = 4, timeout: int = 5, packet_size: int = 56) -> dict:
    """
    Ping a host and return latency / packet-loss stats.
    Returns:
        {
            "reachable":   bool,
            "latency_ms":  float | None,   # average RTT
            "packet_loss": float,          # 0.0 – 100.0 %
        }
    """
    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), "-l", str(packet_size), host]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout), "-s", str(packet_size), host]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout * count + 5,
        )
        # Decode robustly regardless of system locale
        def _decode(b):
            if b is None:
                return ""
            # cp850 = Windows OEM (German cmd), cp1252 = Windows ANSI
            for enc in ("utf-8", "cp850", "cp1252", "latin-1"):
                try:
                    return b.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    pass
            return b.decode("utf-8", errors="replace")

        output = _decode(result.stdout) + _decode(result.stderr)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {"reachable": False, "latency_ms": None, "packet_loss": 100.0}

    # Parse packet loss
    # EN: "0% packet loss" / "0% loss"
    # DE: "0% Verlust"
    loss = 100.0
    loss_match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:packet\s+)?(?:loss|Verlust)", output, re.IGNORECASE)
    if loss_match:
        loss = float(loss_match.group(1))

    # Parse average RTT
    latency: Optional[float] = None
    # Linux/macOS: "rtt min/avg/max/mdev = 1.2/2.3/3.4/0.5 ms"
    rtt_match = re.search(r"min/avg/max.*?=\s*[\d.]+/([\d.]+)/", output)
    if rtt_match:
        latency = float(rtt_match.group(1))
    else:
        # Windows EN: "Average = 2ms"
        # Windows DE: "Durchschnitt = 2ms" or "Mittelwert = 2ms"
        avg_match = re.search(
            r"(?:Average|Durchschnitt|Mittelwert)\s*=\s*(\d+)\s*ms",
            output, re.IGNORECASE
        )
        if avg_match:
            latency = float(avg_match.group(1))
        elif re.search(r"Zeit\s*<\s*1\s*ms", output, re.IGNORECASE):
            # German Windows: "Zeit<1ms" means sub-millisecond, use 0.5
            latency = 0.5

    reachable = loss < 100.0
    return {"reachable": reachable, "latency_ms": latency, "packet_loss": loss}
