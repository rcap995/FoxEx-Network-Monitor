"""WMI monitoring for Windows devices (requires 'wmi' package on Windows)."""
import logging

log = logging.getLogger(__name__)

WMI_METRICS = [
    {"key": "cpu_load",      "wmi_class": "Win32_Processor",       "prop": "LoadPercentage",  "unit": "%"},
    {"key": "mem_free_mb",   "wmi_class": "Win32_OperatingSystem",  "prop": "FreePhysicalMemory", "unit": "KB"},
    {"key": "mem_total_mb",  "wmi_class": "Win32_OperatingSystem",  "prop": "TotalVisibleMemorySize", "unit": "KB"},
    {"key": "os_caption",    "wmi_class": "Win32_OperatingSystem",  "prop": "Caption",         "unit": ""},
    {"key": "uptime_s",      "wmi_class": "Win32_OperatingSystem",  "prop": "LastBootUpTime",  "unit": ""},
]


def collect_wmi(host: str, username: str = None, password: str = None) -> list[dict]:
    """
    Query WMI metrics from a remote Windows host.
    Requires: pip install wmi pywin32  (Windows only)
    """
    try:
        import wmi
    except ImportError:
        return [{"key": "error", "name": "WMI nicht verfügbar",
                 "unit": "", "value_float": None,
                 "value_str": "wmi-Paket fehlt. 'pip install wmi' ausführen.",
                 "error": "ImportError"}]

    results = []
    try:
        if host in ("localhost", "127.0.0.1") and not username:
            conn = wmi.WMI()
        else:
            conn = wmi.WMI(host, user=username, password=password)

        for m in WMI_METRICS:
            entry = {"key": m["key"], "name": m["key"], "unit": m["unit"],
                     "value_float": None, "value_str": None, "error": None}
            try:
                objs = conn.query(f"SELECT {m['prop']} FROM {m['wmi_class']}")
                if objs:
                    raw = getattr(objs[0], m["prop"], None)
                    try:
                        entry["value_float"] = float(raw)
                        entry["value_str"] = str(raw)
                    except (TypeError, ValueError):
                        entry["value_str"] = str(raw)
            except Exception as e:
                entry["error"] = str(e)
            results.append(entry)
    except Exception as e:
        log.error("WMI connection to %s failed: %s", host, e)
        results.append({"key": "connection", "name": "Verbindung",
                        "unit": "", "value_float": None,
                        "value_str": None, "error": str(e)})
    return results
