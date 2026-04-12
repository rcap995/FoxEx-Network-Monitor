"""Background monitoring scheduler using APScheduler."""
import logging
import smtplib
import ssl as _ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app import crud
from app.monitoring.icmp_check import ping
from app.monitoring.snmp_check import collect_snmp
from app.monitoring.tcp_check import tcp_check
from app.monitoring.http_check import http_check
from app.monitoring.ssh_check import ssh_check
from app.monitoring.wmi_check import collect_wmi
from app.monitoring.snmp_check import collect_snmp_template
from app.monitoring.dns_check import dns_check
from app.monitoring.ssh_service_check import ssh_service_check

log = logging.getLogger(__name__)
_scheduler: Optional[BackgroundScheduler] = None


def _evaluate_icmp_alerts(device_id: int, latency_ms, reachable: bool):
    """Evaluate ICMP threshold rules and update icmp_alert_states."""
    rules = crud.get_icmp_alert_rules(device_id)
    if not rules:
        crud.set_icmp_alert_state(device_id, 0, None, None)
        return
    now = datetime.utcnow().isoformat()
    # Build a pseudo result dict compatible with _rule_triggered
    if latency_ms is not None:
        r = {"value_str": str(latency_ms), "value_float": latency_ms, "error": None}
    else:
        r = {"value_str": None, "value_float": None, "error": "no reply" if not reachable else None}
    worst_sev = None
    for rule in rules:
        if _rule_triggered(rule, r):
            sev = rule["severity"]
            if worst_sev is None or _SEV_RANK.get(sev, 0) > _SEV_RANK.get(worst_sev, 0):
                worst_sev = sev
    triggered = worst_sev is not None
    crud.set_icmp_alert_state(device_id, 1 if triggered else 0,
                              worst_sev, now if triggered else None)


def _run_icmp(device_id: int):
    device = crud.get_device(device_id)
    if not device or not device["is_active"] or not device["icmp_enabled"]:
        return
    pkt_size = int(crud.get_setting("icmp.packet_size", "56"))
    pkt_count = int(crud.get_setting("icmp.count", "4"))
    pkt_timeout = int(crud.get_setting("icmp.timeout", "5"))
    result = ping(device["ip_address"], count=pkt_count, timeout=pkt_timeout, packet_size=pkt_size)
    now = datetime.utcnow().isoformat()
    status = "online" if result["reachable"] else "offline"
    crud.update_device_status(device_id, status, now if result["reachable"] else None)
    crud.add_metric(device_id, "icmp_latency",
                    result["latency_ms"],
                    str(result["latency_ms"]) if result["latency_ms"] is not None else None,
                    "ms", now)
    crud.add_metric(device_id, "icmp_packet_loss",
                    result["packet_loss"],
                    f"{result['packet_loss']}%",
                    "%", now)
    _evaluate_icmp_alerts(device_id, result["latency_ms"], result["reachable"])

    # Skip all widget notifications during maintenance window
    _maintenance = crud.is_in_maintenance(device_id)

    # Widget notifications: device status
    if not result["reachable"]:
        if _maintenance:
            crud.resolve_active_alert("status", device["ip_address"])
        else:
            _status_rule = crud.get_widget_notification_rule("status")
            _custom_msg  = (_status_rule or {}).get("message", "").strip()
            _body = (
                _custom_msg
                or f"Gerät '{device['name']}' ({device['ip_address']}) ist nicht erreichbar.\n\n"
                   f"Zeit: {now}\n\nFoxEx Network Monitor"
            )
            _evaluate_widget_notification(
                "status",
                triggered=True,
                subject=f"FoxEx Monitor – Gerät offline: {device['name']}",
                body_text=_body,
                exception_value=device["ip_address"],
                entity_name=device["name"],
            )
    else:
        crud.resolve_active_alert("status", device["ip_address"])

    # Widget notification: per-device latency threshold
    lat_rule = crud.get_widget_notification_rule("device_latency")
    if lat_rule and lat_rule.get("enabled") and result["latency_ms"] is not None:
        try:
            thr = float(lat_rule.get("threshold") or 0)
            triggered = thr > 0 and result["latency_ms"] > thr
        except (ValueError, TypeError):
            triggered = False
        if triggered and not _maintenance:
            _evaluate_widget_notification(
                "device_latency",
                triggered=True,
                subject=f"FoxEx Monitor – Latenz-Schwellwert: {device['name']}",
                body_text=(
                    f"Gerät '{device['name']}' ({device['ip_address']}) überschreitet den Latenz-Schwellwert.\n\n"
                    f"Aktuelle Latenz: {result['latency_ms']} ms\n"
                    f"Schwellwert:     {lat_rule.get('threshold')} ms\n\n"
                    "FoxEx Network Monitor"
                ),
                exception_value=device["ip_address"],
                entity_name=device["name"],
            )
        elif not triggered:
            crud.resolve_active_alert("device_latency", device["ip_address"])

    _check_avg_notifications()
    log.debug("ICMP %s (%s): %s", device["name"], device["ip_address"], result)


_SEV_RANK = {"critical": 2, "warning": 1, "info": 0}


import re as _re


def _rule_triggered(rule: dict, r: dict) -> bool:
    threshold = (rule["threshold"] or "").strip()
    if not threshold:
        return (r.get("error") is not None) or (r.get("value_str") is None)
    op = rule["operator"]
    vs = (r.get("value_str") or "").strip()

    # Extract numeric value from value_str first (what the user sees in the UI).
    # value_float holds the raw SNMP integer which can differ from the formatted
    # display value (e.g. raw=780, displayed="7.8%") — never compare against raw.
    val: float | None = None
    m = _re.match(r'^-?[\d.]+', vs)
    if m:
        try:
            val = float(m.group())
        except ValueError:
            pass
    if val is None:
        vf = r.get("value_float")
        if vf is not None:
            try:
                val = float(vf)
            except (ValueError, TypeError):
                pass

    try:
        tval = float(threshold)
        if val is not None:
            if op == ">":  return val > tval
            if op == "<":  return val < tval
            if op == "=":  return abs(val - tval) < 1e-9
            if op == "!=": return abs(val - tval) >= 1e-9
    except (ValueError, TypeError):
        pass

    # String fallback for text values (e.g. "online", "offline")
    if op == "=":  return vs == threshold
    if op == "!=": return vs != threshold
    return False


def _evaluate_alerts(device_id: int, results: list[dict]) -> str | None:
    """Evaluate multi-rule SNMP alerts and persist worst triggered severity per entry.
    Returns the worst severity triggered across all entries, or None if none triggered."""
    groups = crud.get_snmp_alerts_grouped(device_id)
    if not groups:
        return None
    entry_map = {g["entry_id"]: g for g in groups if g["enabled"]}
    if not entry_map:
        return None
    now = datetime.utcnow().isoformat()
    device_worst_sev = None
    for r in results:
        entry_id = r.get("id")
        group = entry_map.get(entry_id)
        if not group or not group["rules"]:
            continue
        worst_sev = None
        for rule in group["rules"]:
            if _rule_triggered(rule, r):
                sev = rule["severity"]
                if worst_sev is None or _SEV_RANK.get(sev, 0) > _SEV_RANK.get(worst_sev, 0):
                    worst_sev = sev
        triggered = worst_sev is not None
        crud.set_alert_state(device_id, entry_id,
                             1 if triggered else 0,
                             worst_sev,
                             now if triggered else None)
        if worst_sev is not None:
            if device_worst_sev is None or _SEV_RANK.get(worst_sev, 0) > _SEV_RANK.get(device_worst_sev, 0):
                device_worst_sev = worst_sev
    return device_worst_sev


def _run_snmp(device_id: int):
    device = crud.get_device(device_id)
    if not device or not device["is_active"] or not device["snmp_enabled"]:
        return
    now = datetime.utcnow().isoformat()
    _maintenance = crud.is_in_maintenance(device_id)
    worst_sev = None
    template_ids = crud.get_device_template_ids(device_id)
    if template_ids:
        # Template-based polling (new approach)
        all_entries = []
        for tid in template_ids:
            all_entries.extend(crud.get_template_entries(tid))
        if all_entries:
            results = collect_snmp_template(
                device["ip_address"], device["snmp_community"], device["snmp_port"], all_entries
            )
            for r in results:
                if r["error"] is None:
                    crud.add_metric(device_id, f"snmp_tpl_{r['id']}",
                                    r["value_float"], r["value_str"], r["unit"], now)
            worst_sev = _evaluate_alerts(device_id, results)
            log.debug("SNMP-TPL %s: %d metrics from %d templates",
                      device["name"], len(all_entries), len(template_ids))
    else:
        # Fallback: hardcoded SNMP_METRICS (backward compat)
        disabled = crud.get_snmp_disabled(device_id)
        results = collect_snmp(device["ip_address"], device["snmp_community"], device["snmp_port"],
                               disabled_keys=disabled)
        for r in results:
            if r["error"] is None:
                crud.add_metric(device_id, f"snmp_{r['key']}",
                                r["value_float"], r["value_str"], r["unit"], now)
        log.debug("SNMP %s: %d metrics collected (fallback)", device["name"], len(results))

    # Widget notification: snmp (based on worst severity across all triggered entries)
    snmp_rule = crud.get_widget_notification_rule("snmp")
    if snmp_rule and snmp_rule.get("enabled") and worst_sev is not None:
        sev_filter = (snmp_rule.get("severity_filter") or "warning").lower()
        notif_triggered = _SEV_RANK.get(worst_sev, 0) >= _SEV_RANK.get(sev_filter, 1)
        if notif_triggered and not _maintenance:
            _evaluate_widget_notification(
                "snmp",
                triggered=True,
                subject=f"FoxEx Monitor – SNMP-Alert: {device['name']}",
                body_text=(
                    f"SNMP-Alert für Gerät '{device['name']}' ({device['ip_address']}).\n\n"
                    f"Schweregrad: {worst_sev}\n\n"
                    "FoxEx Network Monitor"
                ),
                exception_value=device["ip_address"],
                entity_name=device["name"],
            )
        elif not notif_triggered:
            crud.resolve_active_alert("snmp", device["ip_address"])
    elif worst_sev is None:
        crud.resolve_active_alert("snmp", device["ip_address"])


def _run_tcp(device_id: int):
    device = crud.get_device(device_id)
    if not device or not device["is_active"] or not device["tcp_enabled"]:
        return
    result = tcp_check(device["ip_address"], device["tcp_port"])
    now = datetime.utcnow().isoformat()
    crud.add_metric(device_id, "tcp_connect_ms",
                    result["connect_ms"], str(result["connect_ms"]) if result["connect_ms"] else None,
                    "ms", now)
    crud.add_metric(device_id, "tcp_reachable",
                    1.0 if result["reachable"] else 0.0,
                    "open" if result["reachable"] else "closed",
                    "", now)
    log.debug("TCP %s:%s -> %s", device["ip_address"], device["tcp_port"], result)


def _run_http(device_id: int):
    device = crud.get_device(device_id)
    if not device or not device["is_active"] or not device["http_enabled"] or not device["http_url"]:
        return
    result = http_check(device["http_url"])
    now = datetime.utcnow().isoformat()
    crud.add_metric(device_id, "http_response_ms",
                    result["response_ms"], str(result["response_ms"]) if result["response_ms"] else None,
                    "ms", now)
    crud.add_metric(device_id, "http_status_code",
                    float(result["status_code"]) if result["status_code"] else None,
                    str(result["status_code"]) if result["status_code"] else "error",
                    "", now)
    log.debug("HTTP %s -> %s %sms", device["http_url"], result.get("status_code"), result.get("response_ms"))


def _run_ssh(device_id: int):
    device = crud.get_device(device_id)
    if not device or not device["is_active"] or not device.get("ssh_enabled"):
        return
    result = ssh_check(device["ip_address"], device.get("ssh_port", 22))
    now = datetime.utcnow().isoformat()
    crud.add_metric(device_id, "ssh_connect_ms",
                    result["connect_ms"], str(result["connect_ms"]) if result["connect_ms"] else None,
                    "ms", now)
    crud.add_metric(device_id, "ssh_reachable",
                    1.0 if result["reachable"] else 0.0,
                    result.get("banner") or ("open" if result["reachable"] else "closed"),
                    "", now)
    log.debug("SSH %s:%s -> %s banner=%s",
              device["ip_address"], device.get("ssh_port", 22),
              result["reachable"], result.get("banner"))


def _run_wmi(device_id: int):
    device = crud.get_device(device_id)
    if not device or not device["is_active"] or not device.get("wmi_enabled"):
        return
    results = collect_wmi(
        device["ip_address"],
        username=device.get("wmi_username") or None,
        password=device.get("wmi_password") or None,
    )
    now = datetime.utcnow().isoformat()
    for r in results:
        if r["error"] is None and r["value_float"] is not None:
            crud.add_metric(device_id, f"wmi_{r['key']}",
                            r["value_float"], r["value_str"], r["unit"], now)
    log.debug("WMI %s: %d metrics", device["name"], len(results))


def _schedule_device(device: dict):
    if not _scheduler:
        return
    now = datetime.now(timezone.utc)
    if device["icmp_enabled"]:
        job_id = f"icmp_{device['id']}"
        _scheduler.add_job(_run_icmp, IntervalTrigger(seconds=device["icmp_interval"]),
                           id=job_id, args=[device["id"]],
                           replace_existing=True, max_instances=1,
                           next_run_time=now)
    if device["snmp_enabled"]:
        job_id = f"snmp_{device['id']}"
        _scheduler.add_job(_run_snmp, IntervalTrigger(seconds=device["snmp_interval"]),
                           id=job_id, args=[device["id"]],
                           replace_existing=True, max_instances=1,
                           next_run_time=now)
    if device["tcp_enabled"]:
        job_id = f"tcp_{device['id']}"
        _scheduler.add_job(_run_tcp, IntervalTrigger(seconds=device["tcp_interval"]),
                           id=job_id, args=[device["id"]],
                           replace_existing=True, max_instances=1,
                           next_run_time=now)
    if device["http_enabled"]:
        job_id = f"http_{device['id']}"
        _scheduler.add_job(_run_http, IntervalTrigger(seconds=device["http_interval"]),
                           id=job_id, args=[device["id"]],
                           replace_existing=True, max_instances=1,
                           next_run_time=now)
    if device.get("ssh_enabled"):
        job_id = f"ssh_{device['id']}"
        _scheduler.add_job(_run_ssh, IntervalTrigger(seconds=device.get("ssh_interval", 60)),
                           id=job_id, args=[device["id"]],
                           replace_existing=True, max_instances=1,
                           next_run_time=now)
    if device.get("wmi_enabled"):
        job_id = f"wmi_{device['id']}"
        _scheduler.add_job(_run_wmi, IntervalTrigger(seconds=device.get("wmi_interval", 300)),
                           id=job_id, args=[device["id"]],
                           replace_existing=True, max_instances=1,
                           next_run_time=now)


def schedule_device(device: dict):
    _schedule_device(device)


def trigger_all_now() -> int:
    """Immediately re-schedule all active monitoring jobs."""
    if not _scheduler:
        return 0
    now = datetime.now(timezone.utc)
    count = 0
    for job in _scheduler.get_jobs():
        try:
            _scheduler.modify_job(job.id, next_run_time=now)
            count += 1
        except Exception:
            pass
    return count


def trigger_device_now(device_id: int) -> int:
    """Immediately trigger all monitoring jobs for one device."""
    if not _scheduler:
        return 0
    now = datetime.now(timezone.utc)
    count = 0
    for prefix in ("icmp", "snmp", "tcp", "http", "ssh", "wmi"):
        job = _scheduler.get_job(f"{prefix}_{device_id}")
        if job:
            _scheduler.modify_job(job.id, next_run_time=now)
            count += 1
    return count


def run_device_check(device_id: int, method: str) -> bool:
    """Immediately run one specific check for a device. Returns True if executed."""
    fns = {
        'icmp': _run_icmp, 'snmp': _run_snmp, 'tcp': _run_tcp,
        'http': _run_http, 'ssh': _run_ssh,   'wmi': _run_wmi,
    }
    fn = fns.get(method)
    if not fn:
        return False
    fn(device_id)
    return True


def unschedule_device(device_id: int):
    if not _scheduler:
        return
    for prefix in ("icmp", "snmp", "tcp", "http", "ssh", "wmi"):
        job_id = f"{prefix}_{device_id}"
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)


def _send_widget_email(subject: str, body_text: str):
    """Send a notification e-mail using stored SMTP settings. Silently fails if not configured."""
    try:
        enabled = crud.get_setting("mail.notify.enabled", "0")
        if enabled != "1":
            return
        host     = crud.get_setting("mail.notify.smtp_host", "").strip()
        port     = int(crud.get_setting("mail.notify.smtp_port", "587") or 587)
        enc      = crud.get_setting("mail.notify.encryption", "starttls").strip()
        user     = crud.get_setting("mail.notify.username", "").strip()
        pwd      = crud.get_setting("mail.notify.password", "")
        from_addr = crud.get_setting("mail.notify.from", "").strip() or user
        to_addr   = crud.get_setting("mail.notify.to", "").strip()
        if not host or not to_addr:
            return
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"]    = from_addr
        msg["To"]      = to_addr
        msg.set_content(body_text)
        ctx = _ssl.create_default_context()
        if enc == "ssl":
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as smtp:
                if user:
                    smtp.login(user, pwd)
                smtp.send_message(msg)
        elif enc == "starttls":
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.starttls(context=ctx)
                if user:
                    smtp.login(user, pwd)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                if user:
                    smtp.login(user, pwd)
                smtp.send_message(msg)
        log.info("Widget notification email sent: %s", subject)
    except Exception as exc:
        log.warning("Widget notification email failed: %s", exc)


def _evaluate_widget_notification(widget_type: str, triggered: bool,
                                   subject: str = "", body_text: str = "",
                                   exception_value: str = "",
                                   entity_name: str = ""):
    """Check debounce timer and send email if all conditions are met.
    Also tracks active alerts and respects acknowledgments."""
    try:
        entity_id = exception_value or "global"
        rule = crud.get_widget_notification_rule(widget_type)

        if not triggered:
            # Alert resolved: clear active alert and debounce state
            crud.resolve_active_alert(widget_type, entity_id)
            state = crud.get_widget_notification_state(widget_type)
            if state and state.get("is_triggered"):
                crud.set_widget_notification_state(widget_type, 0, None,
                                                   state.get("last_sent_at"))
            return

        # Triggered: upsert active alert (so it appears in dashboard even without rules)
        crud.upsert_active_alert(widget_type, entity_id,
                                 entity_name or exception_value)

        if not rule or not rule.get("enabled"):
            return

        # Check exceptions list
        if exception_value:
            exc_list = crud.get_widget_notification_exceptions(rule["id"])
            for exc in exc_list:
                if exc["value"].strip().lower() == exception_value.strip().lower():
                    return

        state = crud.get_widget_notification_state(widget_type)
        now   = datetime.utcnow()

        # Determine first_triggered_at
        first_ts = (state["first_triggered_at"]
                    if state and state.get("first_triggered_at")
                    else now.isoformat())
        if not state or not state.get("is_triggered"):
            crud.set_widget_notification_state(widget_type, 1, first_ts,
                                               state["last_sent_at"] if state else None)

        # Check minimum sustained duration
        min_dur = int(rule.get("min_duration_minutes") or 0)
        if min_dur > 0:
            first_dt = datetime.fromisoformat(first_ts)
            if (now - first_dt).total_seconds() < min_dur * 60:
                return

        # Cooldown: wait at least max(min_dur*60, 300) seconds between mails
        cooldown_s = max(min_dur * 60, 300)
        last_sent  = state["last_sent_at"] if state else None
        if last_sent:
            try:
                if (now - datetime.fromisoformat(last_sent)).total_seconds() < cooldown_s:
                    return
            except ValueError:
                pass

        # Skip email if alert is acknowledged
        if crud.is_alert_acked(widget_type, entity_id):
            return

        _send_widget_email(subject, body_text)
        crud.set_widget_notification_state(widget_type, 1, first_ts, now.isoformat())
    except Exception as exc:
        log.warning("_evaluate_widget_notification(%s) error: %s", widget_type, exc)


# ── DNS Monitor ────────────────────────────────────────────────

def _run_dns_monitor(monitor_id: int):
    monitor = crud.get_url_monitor(monitor_id)
    if not monitor or not monitor.get("enabled"):
        return
    result  = dns_check(monitor["url"])
    now     = datetime.utcnow().isoformat()
    crud.update_url_monitor_status(monitor_id, result["status"], result["resolved_ip"], now)
    crud.add_url_monitor_result(monitor_id, result["resolved_ip"],
                                result["status"], result["response_ms"])
    if result["status"] == "offline":
        if crud.is_in_maintenance():
            crud.resolve_active_alert("dns", monitor["url"])
        else:
            _evaluate_widget_notification(
                "dns",
                triggered=True,
                subject=f"FoxEx Monitor – DNS Offline: {monitor['name']}",
                body_text=(
                    f"URL-Monitor '{monitor['name']}' ist nicht erreichbar.\n\n"
                    f"URL: {monitor['url']}\n"
                    f"Zeit: {now}\n\n"
                    "FoxEx Network Monitor"
                ),
                exception_value=monitor["url"],
                entity_name=monitor["name"],
            )
    else:
        _evaluate_widget_notification("dns", triggered=False, exception_value=monitor["url"])
    log.debug("DNS %s (%s): %s", monitor["name"], monitor["url"], result["status"])


def _schedule_dns_monitor(monitor: dict):
    if not _scheduler:
        return
    _scheduler.add_job(
        _run_dns_monitor,
        IntervalTrigger(seconds=monitor["interval_s"]),
        id=f"dns_mon_{monitor['id']}",
        args=[monitor["id"]],
        replace_existing=True, max_instances=1,
        next_run_time=datetime.now(timezone.utc),
    )


def schedule_dns_monitor(monitor: dict):
    _schedule_dns_monitor(monitor)


def unschedule_dns_monitor(monitor_id: int):
    if not _scheduler:
        return
    job_id = f"dns_mon_{monitor_id}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)


# ── Avg-metric notification checks (run after each ICMP batch) ─

def _check_avg_notifications():
    """Evaluate avg-latency and avg-packet-loss widget notifications."""
    try:
        from app.database import get_db
        now = datetime.utcnow()
        cutoff = (now.replace(microsecond=0).isoformat())
        # Avg latency over the last 5 minutes (from all devices)
        with get_db() as db:
            row = db.execute("""
                SELECT AVG(value_float) FROM metric_history
                WHERE metric_name='icmp_latency' AND value_float IS NOT NULL
                  AND timestamp >= datetime('now','-5 minutes')
            """).fetchone()
            avg_lat = row[0] if row and row[0] is not None else None

            row2 = db.execute("""
                SELECT AVG(value_float) FROM metric_history
                WHERE metric_name='icmp_packet_loss' AND value_float IS NOT NULL
                  AND timestamp >= datetime('now','-5 minutes')
            """).fetchone()
            avg_loss = row2[0] if row2 and row2[0] is not None else None

        # icmp_avg notification
        lat_rule = crud.get_widget_notification_rule("icmp_avg")
        if lat_rule and lat_rule.get("enabled") and avg_lat is not None:
            try:
                thr = float(lat_rule.get("threshold") or 0)
                triggered = thr > 0 and avg_lat > thr
            except (ValueError, TypeError):
                triggered = False
            _evaluate_widget_notification(
                "icmp_avg", triggered,
                subject=f"FoxEx Monitor – Ø Latenz erhöht ({avg_lat:.1f} ms)",
                body_text=(
                    f"Der Ø Latenz-Durchschnitt aller Geräte überschreitet den Schwellwert.\n\n"
                    f"Aktueller Wert: {avg_lat:.1f} ms\n"
                    f"Schwellwert:    {lat_rule.get('threshold')} ms\n\n"
                    "FoxEx Network Monitor"
                ),
            )

        # packet_loss notification
        loss_rule = crud.get_widget_notification_rule("packet_loss")
        if loss_rule and loss_rule.get("enabled") and avg_loss is not None:
            try:
                thr = float(loss_rule.get("threshold") or 0)
                triggered = thr >= 0 and avg_loss > thr
            except (ValueError, TypeError):
                triggered = False
            _evaluate_widget_notification(
                "packet_loss", triggered,
                subject=f"FoxEx Monitor – Ø Paketverlust erhöht ({avg_loss:.1f}%)",
                body_text=(
                    f"Der Ø Paketverlust aller Geräte überschreitet den Schwellwert.\n\n"
                    f"Aktueller Wert: {avg_loss:.1f}%\n"
                    f"Schwellwert:    {loss_rule.get('threshold')}%\n\n"
                    "FoxEx Network Monitor"
                ),
            )
    except Exception as exc:
        log.warning("_check_avg_notifications error: %s", exc)


def _run_ssh_service(monitor_id: int):
    monitor = crud.get_ssh_service_monitor(monitor_id)
    if not monitor or not monitor["enabled"]:
        return
    result = ssh_service_check(
        monitor["host"], monitor["port"],
        monitor["username"], monitor["password"],
        monitor["service_name"],
    )
    crud.update_ssh_service_status(
        monitor_id, result["status"], result["output"], result["response_ms"]
    )
    triggered = result["status"] != "active"
    entity_id  = f"{monitor['host']}:{monitor['service_name']}"
    if triggered:
        _evaluate_widget_notification(
            "ssh_service",
            triggered=True,
            subject=f"FoxEx Monitor – Dienst nicht aktiv: {monitor['service_name']} ({monitor['host']})",
            body_text=(
                f"Dienst '{monitor['service_name']}' auf {monitor['host']} ist nicht aktiv.\n\n"
                f"Status:  {result['status']}\n"
                f"Ausgabe: {result['output']}\n\n"
                "FoxEx Network Monitor"
            ),
            exception_value=entity_id,
            entity_name=monitor["name"],
        )
    else:
        _evaluate_widget_notification(
            "ssh_service", triggered=False, exception_value=entity_id
        )
    log.debug("SSH-Service %s/%s → %s (%sms)",
              monitor["host"], monitor["service_name"],
              result["status"], result["response_ms"])


def _schedule_ssh_service_monitor(monitor: dict):
    if not _scheduler:
        return
    _scheduler.add_job(
        _run_ssh_service,
        IntervalTrigger(seconds=max(30, monitor["check_interval"])),
        id=f"ssh_svc_{monitor['id']}",
        args=[monitor["id"]],
        replace_existing=True, max_instances=1,
        next_run_time=datetime.now(timezone.utc),
    )


def schedule_ssh_service_monitor(monitor: dict):
    _schedule_ssh_service_monitor(monitor)


def unschedule_ssh_service_monitor(monitor_id: int):
    if not _scheduler:
        return
    job_id = f"ssh_svc_{monitor_id}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)


def _prune_metrics():
    """Delete metric_history rows older than 30 days (runs daily)."""
    try:
        crud.prune_old_metrics(days=30)
        log.info("Pruned old metric_history rows.")
    except Exception as exc:
        log.warning("Metric pruning failed: %s", exc)


def _prune_syslog():
    """Delete syslog messages past their retention period (runs hourly)."""
    try:
        crud.prune_syslog_by_retention()
        log.debug("Syslog retention pruning complete.")
    except Exception as exc:
        log.warning("Syslog pruning failed: %s", exc)


def _prune_traps():
    """Delete SNMP trap records older than 30 days (runs daily)."""
    try:
        crud.prune_snmp_traps(days=30)
        log.debug("SNMP trap pruning complete.")
    except Exception as exc:
        log.warning("SNMP trap pruning failed: %s", exc)


def start_scheduler():
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.start()
    devices = crud.get_all_devices(active_only=True)
    for device in devices:
        _schedule_device(device)
    # DNS monitors
    monitors = crud.get_url_monitors(enabled_only=True)
    for m in monitors:
        _schedule_dns_monitor(m)
    # Daily pruning of old metrics
    _scheduler.add_job(_prune_metrics, IntervalTrigger(hours=24), id="prune_metrics")
    # Hourly syslog retention pruning
    _scheduler.add_job(_prune_syslog, IntervalTrigger(hours=1), id="prune_syslog")
    # Daily SNMP trap pruning
    _scheduler.add_job(_prune_traps, IntervalTrigger(hours=24), id="prune_traps")
    # SSH service monitors
    ssh_monitors = crud.get_ssh_service_monitors(enabled_only=True)
    for m in ssh_monitors:
        _schedule_ssh_service_monitor(m)
    log.info("Scheduler started. Scheduling %d devices, %d DNS monitors, %d SSH services.",
             len(devices), len(monitors), len(ssh_monitors))
