"""
Syslog UDP collector (RFC 3164 / RFC 5424).
Listens on UDP port 514, matches sender IP to known devices,
stores messages in syslog_messages table and records severity metrics.
"""
import logging
import re
import socket
import threading
from datetime import datetime

log = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_running = False

# Severity names (index = value)
SEVERITY_NAMES = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"]


def _parse_syslog(data: bytes) -> dict:
    """
    Parse a syslog UDP packet (RFC 3164 or RFC 5424).
    Returns dict with facility, severity, hostname, message, raw.
    """
    try:
        raw = data.decode("utf-8", errors="replace").strip()
    except Exception:
        raw = repr(data)

    facility = 1
    severity = 6  # default: info
    hostname = ""
    message = raw

    # RFC 3164: <PRI>TIMESTAMP HOSTNAME MSG
    # RFC 5424: <PRI>VERSION TIMESTAMP HOSTNAME APP-NAME PROCID MSGID ...
    pri_match = re.match(r"^<(\d+)>(.*)", raw, re.DOTALL)
    if pri_match:
        pri_val = int(pri_match.group(1))
        facility = pri_val >> 3
        severity = pri_val & 0x07
        rest = pri_match.group(2)

        # RFC 5424: version digit after PRI
        rfc5424 = re.match(
            r"^(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.*)",
            rest, re.DOTALL
        )
        if rfc5424:
            hostname = rfc5424.group(3) if rfc5424.group(3) != "-" else ""
            message = rfc5424.group(7).lstrip("\xef\xbb\xbf")  # strip UTF-8 BOM
        else:
            # RFC 3164: TIMESTAMP HOSTNAME MSG
            rfc3164 = re.match(
                r"^(\w{3}\s+\d+\s+\d+:\d+:\d+)\s+(\S+)\s+(.*)",
                rest, re.DOTALL
            )
            if rfc3164:
                hostname = rfc3164.group(2)
                message = rfc3164.group(3)
            else:
                message = rest

    sev_name = SEVERITY_NAMES[severity] if severity < len(SEVERITY_NAMES) else str(severity)
    return {
        "facility": facility,
        "severity": severity,
        "severity_name": sev_name,
        "hostname": hostname,
        "message": message,
        "raw": raw,
    }


def _listen(port: int, crud_module):
    global _running
    log.info("Syslog collector listening on UDP :%d", port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(2.0)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError as e:
        log.error("Cannot bind Syslog UDP port %d: %s (try running as root or use port >1024)", port, e)
        return

    while _running:
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            break

        sender_ip = addr[0]
        devices = crud_module.get_all_devices()
        device = next(
            (d for d in devices
             if d.get("syslog_enabled") and
             (d.get("syslog_source_ip") or d["ip_address"]) == sender_ip),
            None
        )
        if not device:
            continue

        msg = _parse_syslog(data)
        now = datetime.utcnow().isoformat()

        crud_module.add_syslog_message(
            device["id"],
            msg["facility"], msg["severity"], msg["severity_name"],
            msg["hostname"], msg["message"], msg["raw"], now
        )

        # Widget notification / active alert for syslog
        _syslog_rule = crud_module.get_widget_notification_rule("syslog")
        if _syslog_rule and _syslog_rule.get("enabled"):
            _SEV_MAP = {"emerg": 0, "alert": 1, "crit": 2, "err": 3,
                        "warning": 4, "notice": 5, "info": 6, "debug": 7}
            _filter_name = (_syslog_rule.get("severity_filter") or "warning").lower()
            _threshold = _SEV_MAP.get(_filter_name, 4)
            if msg["severity"] <= _threshold:
                from app.monitoring.scheduler import _evaluate_widget_notification
                _evaluate_widget_notification(
                    "syslog",
                    triggered=True,
                    subject=f"FoxEx Monitor – Syslog: {device['name']} [{msg['severity_name'].upper()}]",
                    body_text=(
                        f"Syslog-Meldung von '{device['name']}' ({sender_ip}):\n\n"
                        f"Schweregrad: {msg['severity_name'].upper()}\n"
                        f"Nachricht:   {msg['message']}\n\n"
                        "FoxEx Network Monitor"
                    ),
                    exception_value=sender_ip,
                    entity_name=device["name"],
                )

        log.debug("Syslog from %s (%s) sev=%s: %s",
                  sender_ip, device["name"], msg["severity_name"], msg["message"][:80])

    sock.close()
    log.info("Syslog collector stopped.")


def start_syslog_collector(port: int = 514):
    """Start the Syslog UDP listener in a background thread."""
    global _thread, _running
    if _running:
        return
    from app import crud
    _running = True
    _thread = threading.Thread(target=_listen, args=(port, crud), daemon=True, name="syslog-collector")
    _thread.start()


def stop_syslog_collector():
    global _running
    _running = False
