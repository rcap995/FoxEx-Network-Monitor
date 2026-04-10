"""HTTP/HTTPS health check — no external dependencies (uses urllib)."""
import time
import urllib.request
import urllib.error
import ssl


def http_check(url: str, timeout: int = 10, verify_ssl: bool = False) -> dict:
    """
    Perform an HTTP(S) GET and return availability + response metrics.
    Returns:
        {
            "reachable":       bool,
            "status_code":     int | None,
            "response_ms":     float | None,
            "content_length":  int | None,
            "error":           str | None,
        }
    """
    ctx = ssl.create_default_context()
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "FoxEx-NetworkMonitor/1.0"},
        method="GET",
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            elapsed = (time.monotonic() - start) * 1000
            body = resp.read()
            return {
                "reachable":      True,
                "status_code":    resp.status,
                "response_ms":    round(elapsed, 2),
                "content_length": len(body),
                "error":          None,
            }
    except urllib.error.HTTPError as e:
        elapsed = (time.monotonic() - start) * 1000
        # HTTP errors (4xx/5xx) still mean the server responded
        return {
            "reachable":      True,
            "status_code":    e.code,
            "response_ms":    round(elapsed, 2),
            "content_length": None,
            "error":          str(e.reason),
        }
    except Exception as e:
        return {
            "reachable":      False,
            "status_code":    None,
            "response_ms":    None,
            "content_length": None,
            "error":          str(e),
        }
