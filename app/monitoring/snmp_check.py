"""SNMPv2c monitoring via puresnmp 2.x"""
import asyncio
import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

SNMP_METRICS = [
    {"key": "sysDescr",        "oid": "1.3.6.1.2.1.1.1.0",          "name": "System Description",    "unit": ""},
    {"key": "sysUpTime",       "oid": "1.3.6.1.2.1.1.3.0",          "name": "System Uptime",          "unit": "timeticks"},
    {"key": "sysContact",      "oid": "1.3.6.1.2.1.1.4.0",          "name": "System Contact",         "unit": ""},
    {"key": "sysLocation",     "oid": "1.3.6.1.2.1.1.6.0",          "name": "System Location",        "unit": ""},
    {"key": "cpuLoad",         "oid": "1.3.6.1.2.1.25.3.3.1.2.1",   "name": "CPU Last Minute %",      "unit": "%"},
    {"key": "memTotal",        "oid": "1.3.6.1.2.1.25.2.2.0",       "name": "Total Memory",           "unit": "KB"},
    {"key": "ifOperStatus",    "oid": "1.3.6.1.2.1.2.2.1.8.1",      "name": "Interface 1 Status",     "unit": ""},
    {"key": "ifInOctets",      "oid": "1.3.6.1.2.1.2.2.1.10.1",     "name": "IF1 In Bytes",           "unit": "bytes"},
    {"key": "ifOutOctets",     "oid": "1.3.6.1.2.1.2.2.1.16.1",     "name": "IF1 Out Bytes",          "unit": "bytes"},
    {"key": "ifInErrors",      "oid": "1.3.6.1.2.1.2.2.1.14.1",     "name": "IF1 In Errors",          "unit": ""},
    {"key": "ifOutErrors",     "oid": "1.3.6.1.2.1.2.2.1.20.1",     "name": "IF1 Out Errors",         "unit": ""},
    {"key": "tcpCurrEstab",    "oid": "1.3.6.1.2.1.6.9.0",          "name": "TCP Connections",        "unit": ""},
    {"key": "ipForwDatagrams", "oid": "1.3.6.1.2.1.4.6.0",          "name": "IP Forwarded Datagrams", "unit": ""},
]


def _format_value(raw: Any) -> "tuple[Optional[float], str]":
    if raw is None:
        return None, ""
    # puresnmp 2.x returns typed objects — extract python value
    try:
        raw = raw.pythonize()
    except AttributeError:
        pass
    if isinstance(raw, bytes):
        try:
            return None, raw.decode("utf-8", errors="replace")
        except Exception:
            return None, str(raw)
    try:
        v = int(raw)
        return float(v), str(v)
    except (TypeError, ValueError):
        pass
    try:
        v = float(raw)
        return v, str(raw)
    except (TypeError, ValueError):
        pass
    return None, str(raw)


def _post_format(oid: str, unit: str, value_float: Optional[float], value_str: str) -> str:
    """Return a human-readable display string for well-known OID/unit combinations.

    Only value_str is changed; value_float is intentionally left untouched so
    raw numeric values are still stored in the DB for graphing.
    """
    # ------------------------------------------------------------------ #
    # timeticks  (unit == "timeticks"  OR  OID contains sysUpTime prefix) #
    # ------------------------------------------------------------------ #
    if unit == "timeticks" or "1.3.6.1.2.1.1.3" in oid:
        if value_float is not None:
            try:
                total_seconds = int(value_float) // 100  # timeticks are 1/100 s
                days    = total_seconds // 86400
                remain  = total_seconds % 86400
                hours   = remain // 3600
                remain  = remain % 3600
                minutes = remain // 60
                seconds = remain % 60
                if days > 0:
                    return f"{days}d {hours}h {minutes}m"
                elif hours > 0:
                    return f"{hours}h {minutes}m {seconds}s"
                else:
                    return f"{minutes}m {seconds}s"
            except (TypeError, ValueError):
                pass
        return value_str

    # ------------------------------------------------------------------ #
    # ifOperStatus  (OID contains 2.2.1.8)                                #
    # ------------------------------------------------------------------ #
    if "2.2.1.8" in oid:
        _IF_STATUS = {
            1: "up",
            2: "down",
            3: "testing",
            4: "unknown",
            5: "dormant",
            6: "notPresent",
            7: "lowerLayerDown",
        }
        if value_float is not None:
            return _IF_STATUS.get(int(value_float), value_str)
        return value_str

    # ------------------------------------------------------------------ #
    # bytes unit                                                           #
    # ------------------------------------------------------------------ #
    if unit == "bytes":
        if value_float is not None:
            try:
                v = float(value_float)
                for suffix, threshold in (("TB", 1 << 40), ("GB", 1 << 30),
                                          ("MB", 1 << 20), ("KB", 1 << 10)):
                    if v >= threshold:
                        return f"{v / threshold:.1f} {suffix}"
                return f"{int(v)} B"
            except (TypeError, ValueError):
                pass
        return value_str

    # ------------------------------------------------------------------ #
    # KB unit  (e.g. memTotal — already in kilobytes)                     #
    # ------------------------------------------------------------------ #
    if unit == "KB":
        if value_float is not None:
            try:
                v = float(value_float)  # value is already in KB
                if v >= 1 << 30:        # >= 1 TB (in KB)
                    return f"{v / (1 << 30):.1f} TB"
                elif v >= 1 << 20:      # >= 1 GB (in KB)
                    return f"{v / (1 << 20):.1f} GB"
                elif v >= 1 << 10:      # >= 1 MB (in KB)
                    return f"{v / (1 << 10):.1f} MB"
                else:
                    return f"{v:.0f} KB"
            except (TypeError, ValueError):
                pass
        return value_str

    # ------------------------------------------------------------------ #
    # percentage unit                                                      #
    # ------------------------------------------------------------------ #
    if unit == "%":
        if value_str and not value_str.endswith("%"):
            return f"{value_str}%"
        return value_str

    # ------------------------------------------------------------------ #
    # fallthrough — return unchanged                                       #
    # ------------------------------------------------------------------ #
    return value_str


async def _collect_template_async(host: str, community: str, port: int,
                                   entries: list[dict]) -> list[dict]:
    from puresnmp import Client, V2C, ObjectIdentifier
    client = Client(host, V2C(community), port=port)
    results = []
    for entry in entries:
        oid_str = entry["oid"]
        unit    = entry.get("unit", "")
        r = {
            "id":          entry["id"],
            "label":       entry["label"],
            "oid":         oid_str,
            "unit":        unit,
            "value_float": None,
            "value_str":   None,
            "error":       None,
        }
        try:
            # Determine whether this looks like a scalar OID (.0 suffix) or a
            # table-column OID.  For table OIDs we try the exact OID first so
            # that callers who already include the instance (e.g. ".1") get the
            # right row; if that fails we append ".1" and try once more before
            # giving up.
            is_scalar = oid_str.rstrip(".").endswith(".0")

            raw = None
            last_exc: Optional[Exception] = None

            # --- first attempt: use the OID exactly as provided ---
            try:
                raw = await client.get(ObjectIdentifier(oid_str))
            except Exception as exc:
                last_exc = exc
                log.debug("SNMP-TPL %s %s (exact): %s", host, oid_str, exc)

            # --- fallback for table OIDs: append ".1" (first row) ---
            if raw is None and not is_scalar:
                fallback_oid = oid_str.rstrip(".") + ".1"
                try:
                    raw = await client.get(ObjectIdentifier(fallback_oid))
                    log.debug(
                        "SNMP-TPL %s %s: exact GET failed, succeeded with fallback %s",
                        host, oid_str, fallback_oid,
                    )
                    last_exc = None  # fallback worked — clear the error
                except Exception as exc2:
                    log.debug(
                        "SNMP-TPL %s %s (fallback %s): %s",
                        host, oid_str, fallback_oid, exc2,
                    )
                    # keep last_exc from the original attempt as the reported error

            if raw is not None:
                vf, vs = _format_value(raw)
                r["value_float"] = vf
                r["value_str"]   = _post_format(oid_str, unit, vf, vs)
            else:
                r["error"] = str(last_exc)

        except Exception as exc:
            r["error"] = str(exc)
            log.debug("SNMP-TPL %s %s: %s", host, oid_str, exc)

        results.append(r)
    return results


def collect_snmp_template(host: str, community: str = "public", port: int = 161,
                           entries: list | None = None) -> list[dict]:
    """Poll custom OID template entries. Returns list with value per entry."""
    if not entries:
        return []
    try:
        import puresnmp  # noqa: F401
    except ImportError:
        log.error("puresnmp is not installed")
        return []
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_collect_template_async(host, community, port, entries))
        finally:
            loop.close()
    except Exception as exc:
        log.error("SNMP template collect failed for %s: %s", host, exc)
        return []


async def _collect_async(host: str, community: str, port: int,
                          disabled: set) -> list[dict]:
    from puresnmp import Client, V2C, ObjectIdentifier
    client = Client(host, V2C(community), port=port)
    results = []
    for m in SNMP_METRICS:
        if m["key"] in disabled:
            continue
        r = {
            "key":         m["key"],
            "name":        m["name"],
            "oid":         m["oid"],
            "unit":        m["unit"],
            "value_float": None,
            "value_str":   None,
            "error":       None,
        }
        try:
            raw = await client.get(ObjectIdentifier(m["oid"]))
            vf, vs = _format_value(raw)
            r["value_float"] = vf
            r["value_str"]   = _post_format(m["oid"], m["unit"], vf, vs)
        except Exception as exc:
            r["error"] = str(exc)
            log.debug("SNMP %s %s: %s", host, m["oid"], exc)
        results.append(r)
    return results


def collect_snmp(host: str, community: str = "public", port: int = 161,
                 disabled_keys: list | None = None) -> list[dict]:
    """Synchronous wrapper — safe to call from APScheduler threads."""
    try:
        import puresnmp  # noqa: F401
    except ImportError:
        log.error("puresnmp is not installed")
        return []

    disabled = set(disabled_keys or [])
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                _collect_async(host, community, port, disabled)
            )
        finally:
            loop.close()
    except Exception as exc:
        log.error("SNMP collect failed for %s: %s", host, exc)
        return []
