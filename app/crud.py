"""All database CRUD operations using sqlite3."""
import json
from datetime import datetime, timedelta
from app.database import get_db
from app.models import row_to_dict, rows_to_list


# ── Users ─────────────────────────────────────────────────────

def get_user_by_username(username: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return row_to_dict(row)


def create_user(username: str, hashed_password: str) -> dict:
    with get_db() as db:
        db.execute(
            "INSERT INTO users (username, hashed_password, role) VALUES (?,?,'admin')",
            (username, hashed_password),
        )
        row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return row_to_dict(row)


def create_user_full(username: str, hashed_password: str,
                     full_name: str = "", role: str = "user",
                     force_pw_change: int = 0) -> dict:
    with get_db() as db:
        db.execute(
            "INSERT INTO users (username, hashed_password, full_name, role, force_pw_change) VALUES (?,?,?,?,?)",
            (username, hashed_password, full_name, role, force_pw_change),
        )
        row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return row_to_dict(row)


def get_user(user_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return row_to_dict(row) if row else None


def get_all_users() -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT id, username, full_name, role, force_pw_change, created_at FROM users ORDER BY id"
        ).fetchall()
        return rows_to_list(rows)


def update_user_profile(user_id: int, full_name: str, hashed_password: str | None = None):
    with get_db() as db:
        if hashed_password:
            db.execute(
                "UPDATE users SET full_name=?, hashed_password=?, force_pw_change=0 WHERE id=?",
                (full_name, hashed_password, user_id),
            )
        else:
            db.execute("UPDATE users SET full_name=? WHERE id=?", (full_name, user_id))


def update_user_role(user_id: int, role: str):
    with get_db() as db:
        db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))


def admin_set_user_password(user_id: int, hashed_password: str, force_pw_change: int = 0):
    """Admin resets another user's password (optionally forcing change on next login)."""
    with get_db() as db:
        db.execute(
            "UPDATE users SET hashed_password=?, force_pw_change=? WHERE id=?",
            (hashed_password, force_pw_change, user_id),
        )


def clear_force_pw_change(user_id: int):
    with get_db() as db:
        db.execute("UPDATE users SET force_pw_change=0 WHERE id=?", (user_id,))


def delete_user(user_id: int):
    with get_db() as db:
        db.execute("DELETE FROM users WHERE id=?", (user_id,))


# ── Devices ───────────────────────────────────────────────────

def get_all_devices(active_only: bool = False) -> list[dict]:
    with get_db() as db:
        if active_only:
            rows = db.execute("SELECT * FROM devices WHERE is_active=1 ORDER BY name").fetchall()
        else:
            rows = db.execute("SELECT * FROM devices ORDER BY name").fetchall()
        devices = rows_to_list(rows)
        for d in devices:
            tids = db.execute(
                "SELECT template_id FROM device_snmp_templates WHERE device_id=? ORDER BY template_id",
                (d["id"],)
            ).fetchall()
            d["snmp_template_ids"] = [r[0] for r in tids]
        return devices


def get_device(device_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
        d = row_to_dict(row)
        if d is not None:
            tids = db.execute(
                "SELECT template_id FROM device_snmp_templates WHERE device_id=? ORDER BY template_id",
                (device_id,)
            ).fetchall()
            d["snmp_template_ids"] = [r[0] for r in tids]
        return d


def create_device(data: dict) -> dict:
    with get_db() as db:
        db.execute(
            """INSERT INTO devices
               (name, ip_address, device_type, description,
                snmp_enabled, snmp_community, snmp_port,
                icmp_enabled, icmp_interval, snmp_interval,
                tcp_enabled, tcp_port, tcp_interval,
                http_enabled, http_url, http_interval,
                ssh_enabled, ssh_port, ssh_interval,
                wmi_enabled, wmi_username, wmi_password, wmi_interval,
                netflow_enabled, sflow_enabled,
                syslog_enabled, syslog_port, syslog_source_ip,
                snmp_template_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["name"], data["ip_address"],
                data.get("device_type", "generic"),
                data.get("description", ""),
                1 if data.get("snmp_enabled") else 0,
                data.get("snmp_community", "public"),
                int(data.get("snmp_port", 161)),
                1 if data.get("icmp_enabled", True) else 0,
                int(data.get("icmp_interval", 60)),
                int(data.get("snmp_interval", 300)),
                1 if data.get("tcp_enabled") else 0,
                int(data.get("tcp_port", 80)),
                int(data.get("tcp_interval", 60)),
                1 if data.get("http_enabled") else 0,
                data.get("http_url", ""),
                int(data.get("http_interval", 60)),
                1 if data.get("ssh_enabled") else 0,
                int(data.get("ssh_port", 22)),
                int(data.get("ssh_interval", 60)),
                1 if data.get("wmi_enabled") else 0,
                data.get("wmi_username", ""),
                data.get("wmi_password", ""),
                int(data.get("wmi_interval", 300)),
                1 if data.get("netflow_enabled") else 0,
                1 if data.get("sflow_enabled") else 0,
                1 if data.get("syslog_enabled") else 0,
                int(data.get("syslog_port", 514)),
                data.get("syslog_source_ip", ""),
                data.get("snmp_template_id") or None,
            ),
        )
        row = db.execute("SELECT * FROM devices WHERE id=last_insert_rowid()").fetchone()
        return row_to_dict(row)


def update_device(device_id: int, data: dict) -> dict | None:
    with get_db() as db:
        db.execute(
            """UPDATE devices SET
               name=?, ip_address=?, device_type=?, description=?,
               snmp_enabled=?, snmp_community=?, snmp_port=?,
               icmp_enabled=?, icmp_interval=?, snmp_interval=?,
               tcp_enabled=?, tcp_port=?, tcp_interval=?,
               http_enabled=?, http_url=?, http_interval=?,
               ssh_enabled=?, ssh_port=?, ssh_interval=?,
               wmi_enabled=?, wmi_username=?, wmi_password=?, wmi_interval=?,
               netflow_enabled=?, sflow_enabled=?,
               syslog_enabled=?, syslog_port=?, syslog_source_ip=?,
               snmp_template_id=?,
               is_active=?
               WHERE id=?""",
            (
                data["name"], data["ip_address"],
                data.get("device_type", "generic"),
                data.get("description", ""),
                1 if data.get("snmp_enabled") else 0,
                data.get("snmp_community", "public"),
                int(data.get("snmp_port", 161)),
                1 if data.get("icmp_enabled", True) else 0,
                int(data.get("icmp_interval", 60)),
                int(data.get("snmp_interval", 300)),
                1 if data.get("tcp_enabled") else 0,
                int(data.get("tcp_port", 80)),
                int(data.get("tcp_interval", 60)),
                1 if data.get("http_enabled") else 0,
                data.get("http_url", ""),
                int(data.get("http_interval", 60)),
                1 if data.get("ssh_enabled") else 0,
                int(data.get("ssh_port", 22)),
                int(data.get("ssh_interval", 60)),
                1 if data.get("wmi_enabled") else 0,
                data.get("wmi_username", ""),
                data.get("wmi_password", ""),
                int(data.get("wmi_interval", 300)),
                1 if data.get("netflow_enabled") else 0,
                1 if data.get("sflow_enabled") else 0,
                1 if data.get("syslog_enabled") else 0,
                int(data.get("syslog_port", 514)),
                data.get("syslog_source_ip", ""),
                data.get("snmp_template_id") or None,
                1 if data.get("is_active", True) else 0,
                device_id,
            ),
        )
        row = db.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
        return row_to_dict(row)


def delete_device(device_id: int):
    with get_db() as db:
        db.execute("DELETE FROM devices WHERE id=?", (device_id,))


def update_device_status(device_id: int, status: str, last_seen: str | None = None):
    with get_db() as db:
        if last_seen:
            db.execute(
                "UPDATE devices SET status=?, last_seen=? WHERE id=?",
                (status, last_seen, device_id),
            )
        else:
            db.execute("UPDATE devices SET status=? WHERE id=?", (status, device_id))


def update_device_icon(device_id: int, icon_name: str):
    with get_db() as db:
        db.execute("UPDATE devices SET icon_name=? WHERE id=?", (icon_name, device_id))


# ── Device Notes ──────────────────────────────────────────────

def get_notes(device_id: int) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM device_notes WHERE device_id=? ORDER BY created_at DESC",
            (device_id,),
        ).fetchall()
        return rows_to_list(rows)


def create_note(device_id: int, title: str, content: str) -> dict:
    with get_db() as db:
        db.execute(
            "INSERT INTO device_notes (device_id, title, content) VALUES (?,?,?)",
            (device_id, title, content),
        )
        row = db.execute(
            "SELECT * FROM device_notes WHERE id=last_insert_rowid()"
        ).fetchone()
        return row_to_dict(row)


def delete_note(note_id: int):
    with get_db() as db:
        db.execute("DELETE FROM device_notes WHERE id=?", (note_id,))


# ── Metrics ───────────────────────────────────────────────────

def prune_old_metrics(days: int = 30):
    """Delete metric_history rows older than `days` days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_db() as db:
        db.execute("DELETE FROM metric_history WHERE timestamp < ?", (cutoff,))


def add_metric(device_id: int, metric_name: str, value_float, value_str: str, unit: str, ts: str):
    with get_db() as db:
        db.execute(
            """INSERT INTO metric_history
               (device_id, metric_name, value_float, value_str, unit, timestamp)
               VALUES (?,?,?,?,?,?)""",
            (device_id, metric_name, value_float, value_str, unit, ts),
        )


def get_metrics(device_id: int, metric_name: str | None, hours: int, limit: int) -> list[dict]:
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as db:
        if metric_name:
            rows = db.execute(
                """SELECT * FROM metric_history
                   WHERE device_id=? AND metric_name=? AND timestamp>=?
                   ORDER BY timestamp ASC LIMIT ?""",
                (device_id, metric_name, since, limit),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT * FROM metric_history
                   WHERE device_id=? AND timestamp>=?
                   ORDER BY timestamp ASC LIMIT ?""",
                (device_id, since, limit),
            ).fetchall()
        return rows_to_list(rows)


def get_latest_metrics(device_id: int) -> dict:
    with get_db() as db:
        names = db.execute(
            "SELECT DISTINCT metric_name FROM metric_history WHERE device_id=?",
            (device_id,),
        ).fetchall()
        result = {}
        for (name,) in names:
            row = db.execute(
                """SELECT * FROM metric_history
                   WHERE device_id=? AND metric_name=?
                   ORDER BY timestamp DESC LIMIT 1""",
                (device_id, name),
            ).fetchone()
            if row:
                result[name] = row_to_dict(row)
        return result


def get_latest_latency(device_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute(
            """SELECT * FROM metric_history
               WHERE device_id=? AND metric_name='icmp_latency'
               ORDER BY timestamp DESC LIMIT 1""",
            (device_id,),
        ).fetchone()
        return row_to_dict(row) if row else None


# ── Topology ──────────────────────────────────────────────────

def get_topology() -> dict:
    with get_db() as db:
        row = db.execute("SELECT * FROM topology_maps LIMIT 1").fetchone()
        if not row:
            return {"nodes": [], "edges": []}
        import json
        return json.loads(row["data_json"])


def save_topology(data_json: str):
    with get_db() as db:
        existing = db.execute("SELECT id FROM topology_maps LIMIT 1").fetchone()
        now = datetime.utcnow().isoformat()
        if existing:
            db.execute(
                "UPDATE topology_maps SET data_json=?, updated_at=? WHERE id=?",
                (data_json, now, existing["id"]),
            )
        else:
            db.execute(
                "INSERT INTO topology_maps (data_json, updated_at) VALUES (?,?)",
                (data_json, now),
            )


def get_snmp_disabled(device_id: int) -> list:
    with get_db() as db:
        row = db.execute(
            "SELECT snmp_metrics_disabled FROM devices WHERE id=?", (device_id,)
        ).fetchone()
        if not row or not row[0]:
            return []
        try:
            return json.loads(row[0])
        except Exception:
            return []


def set_snmp_disabled(device_id: int, disabled: list):
    with get_db() as db:
        db.execute(
            "UPDATE devices SET snmp_metrics_disabled=? WHERE id=?",
            (json.dumps(disabled), device_id),
        )


# ── Syslog Messages ───────────────────────────────────────────

def add_syslog_message(device_id: int, facility: int, severity: int,
                       severity_name: str, hostname: str, message: str,
                       raw: str, ts: str):
    with get_db() as db:
        db.execute(
            """INSERT INTO syslog_messages
               (device_id, facility, severity, severity_name, hostname, message, raw, received_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (device_id, facility, severity, severity_name, hostname, message, raw, ts),
        )


def delete_syslog_message(msg_id: int):
    """Resolve (permanently delete) a single syslog message."""
    with get_db() as db:
        db.execute("DELETE FROM syslog_messages WHERE id=?", (msg_id,))


_SYSLOG_SEV_DEFAULTS = {
    "emerg": 0, "alert": 0, "crit": 0, "err": 0, "warning": 0,
    "notice": 1440, "info": 1440, "debug": 1440,
}


def prune_syslog_by_retention():
    """Delete syslog messages older than their configured retention period.
    Retention = 0 means never auto-delete (manual resolve only)."""
    for sev, default_mins in _SYSLOG_SEV_DEFAULTS.items():
        minutes = int(get_setting(f"syslog.retention.{sev}", str(default_mins)))
        if minutes <= 0:
            continue
        cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
        with get_db() as db:
            db.execute(
                "DELETE FROM syslog_messages WHERE severity_name=? AND received_at < ?",
                (sev, cutoff),
            )


def get_syslog_messages(device_id: int, hours: int = 24, limit: int = 200,
                        min_severity: int | None = None) -> list[dict]:
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as db:
        if min_severity is not None:
            rows = db.execute(
                """SELECT * FROM syslog_messages
                   WHERE device_id=? AND received_at>=? AND severity<=?
                   ORDER BY received_at DESC LIMIT ?""",
                (device_id, since, min_severity, limit),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT * FROM syslog_messages
                   WHERE device_id=? AND received_at>=?
                   ORDER BY received_at DESC LIMIT ?""",
                (device_id, since, limit),
            ).fetchall()
        return rows_to_list(rows)


def get_syslog_stats(device_id: int, hours: int = 24) -> dict:
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as db:
        rows = db.execute(
            """SELECT severity_name, COUNT(*) as cnt
               FROM syslog_messages
               WHERE device_id=? AND received_at>=?
               GROUP BY severity_name""",
            (device_id, since),
        ).fetchall()
        return {r["severity_name"]: r["cnt"] for r in rows}


def get_syslog_dashboard_summary(hours: int = 24) -> dict:
    """Severity counts across ALL syslog-enabled devices."""
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as db:
        rows = db.execute(
            """SELECT severity_name, COUNT(*) as cnt
               FROM syslog_messages
               WHERE received_at >= ?
               GROUP BY severity_name""",
            (since,),
        ).fetchall()
    return {r["severity_name"]: r["cnt"] for r in rows}


def get_syslog_all_devices(hours: int = 24, severity_name: str | None = None,
                            limit: int = 300) -> list[dict]:
    """All syslog messages across all devices, with device name."""
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as db:
        if severity_name:
            rows = db.execute(
                """SELECT sm.*, d.name AS device_name, d.ip_address AS device_ip
                   FROM syslog_messages sm
                   JOIN devices d ON d.id = sm.device_id
                   WHERE sm.received_at >= ? AND sm.severity_name = ?
                   ORDER BY sm.received_at DESC LIMIT ?""",
                (since, severity_name, limit),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT sm.*, d.name AS device_name, d.ip_address AS device_ip
                   FROM syslog_messages sm
                   JOIN devices d ON d.id = sm.device_id
                   WHERE sm.received_at >= ?
                   ORDER BY sm.received_at DESC LIMIT ?""",
                (since, limit),
            ).fetchall()
    return rows_to_list(rows)


def ensure_topology_exists():
    with get_db() as db:
        existing = db.execute("SELECT id FROM topology_maps LIMIT 1").fetchone()
        if not existing:
            db.execute("INSERT INTO topology_maps DEFAULT VALUES")


# ── App Settings (key-value store) ────────────────────────────

def get_setting(key: str, default: str = '') -> str:
    with get_db() as db:
        row = db.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default


def set_setting(key: str, value: str):
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?,?)", (key, str(value)))


def get_all_settings() -> dict:
    with get_db() as db:
        rows = db.execute("SELECT key, value FROM app_settings").fetchall()
        return {r[0]: r[1] for r in rows}


# ── Device ↔ SNMP Template assignments ─────────────────────────

def get_device_template_ids(device_id: int) -> list[int]:
    with get_db() as db:
        rows = db.execute(
            "SELECT template_id FROM device_snmp_templates WHERE device_id=? ORDER BY template_id",
            (device_id,)
        ).fetchall()
        return [r[0] for r in rows]


def set_device_templates(device_id: int, template_ids: list[int]):
    with get_db() as db:
        db.execute("DELETE FROM device_snmp_templates WHERE device_id=?", (device_id,))
        for tid in template_ids:
            db.execute(
                "INSERT OR IGNORE INTO device_snmp_templates (device_id, template_id) VALUES (?,?)",
                (device_id, tid)
            )


def get_all_template_entries_for_device(device_id: int) -> list[dict]:
    """All OID entries from every template assigned to a device."""
    with get_db() as db:
        rows = db.execute("""
            SELECT e.id, e.oid, e.label, e.unit, t.name AS template_name
            FROM snmp_oid_entries e
            JOIN snmp_oid_templates t ON t.id = e.template_id
            JOIN device_snmp_templates dst ON dst.template_id = e.template_id
            WHERE dst.device_id = ?
            ORDER BY t.id, e.sort_order, e.id
        """, (device_id,)).fetchall()
        return rows_to_list(rows)


def set_entry_sort_orders(tid: int, ordered_ids: list[int]):
    """Set sort_order for template entries based on given ordered list of IDs."""
    with get_db() as db:
        for pos, eid in enumerate(ordered_ids):
            db.execute(
                "UPDATE snmp_oid_entries SET sort_order=? WHERE id=? AND template_id=?",
                (pos, eid, tid),
            )


# ── SNMP OID Templates ─────────────────────────────────────────

def get_snmp_templates() -> list[dict]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM snmp_oid_templates ORDER BY name").fetchall()
        return rows_to_list(rows)


def get_snmp_template(tid: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM snmp_oid_templates WHERE id=?", (tid,)).fetchone()
        return row_to_dict(row)


def create_snmp_template(name: str, description: str = '') -> dict:
    with get_db() as db:
        db.execute("INSERT INTO snmp_oid_templates (name, description) VALUES (?,?)", (name, description))
        row = db.execute("SELECT * FROM snmp_oid_templates WHERE id=last_insert_rowid()").fetchone()
        return row_to_dict(row)


def update_snmp_template(tid: int, name: str, description: str = ''):
    with get_db() as db:
        db.execute("UPDATE snmp_oid_templates SET name=?, description=? WHERE id=?",
                   (name, description, tid))


def delete_snmp_template(tid: int):
    with get_db() as db:
        db.execute("DELETE FROM snmp_oid_templates WHERE id=?", (tid,))


def get_template_entries(tid: int) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM snmp_oid_entries WHERE template_id=? ORDER BY sort_order, id",
            (tid,),
        ).fetchall()
        return rows_to_list(rows)


def add_template_entry(tid: int, oid: str, label: str, unit: str = '') -> dict:
    with get_db() as db:
        db.execute("INSERT INTO snmp_oid_entries (template_id, oid, label, unit) VALUES (?,?,?,?)",
                   (tid, oid, label, unit))
        row = db.execute("SELECT * FROM snmp_oid_entries WHERE id=last_insert_rowid()").fetchone()
        return row_to_dict(row)


def delete_template_entry(eid: int):
    with get_db() as db:
        db.execute("DELETE FROM snmp_oid_entries WHERE id=?", (eid,))


# ── SNMP Alerts ────────────────────────────────────────────────

def get_snmp_alerts_grouped(device_id: int) -> list[dict]:
    """Returns alert configs grouped by entry_id, with rules list and trigger state."""
    with get_db() as db:
        rules    = db.execute(
            "SELECT id, entry_id, operator, threshold, severity FROM snmp_alerts WHERE device_id=? ORDER BY id",
            (device_id,),
        ).fetchall()
        cfg_rows = db.execute(
            "SELECT entry_id, enabled FROM snmp_alert_entry_cfg WHERE device_id=?",
            (device_id,),
        ).fetchall()
        state_rows = db.execute(
            "SELECT entry_id, triggered, severity AS trig_severity, triggered_at FROM snmp_alert_states WHERE device_id=?",
            (device_id,),
        ).fetchall()
    cfg_map   = {r[0]: r[1] for r in cfg_rows}
    state_map = {r["entry_id"]: dict(r) for r in state_rows}
    rules_by_entry: dict[int, list] = {}
    for r in rules:
        eid = r["entry_id"]
        rules_by_entry.setdefault(eid, []).append(dict(r))
    all_eids = sorted(set(rules_by_entry) | set(cfg_map))
    result = []
    for eid in all_eids:
        st = state_map.get(eid, {})
        result.append({
            "entry_id":       eid,
            "enabled":        cfg_map.get(eid, 1),
            "triggered":      st.get("triggered", 0),
            "trig_severity":  st.get("trig_severity"),
            "triggered_at":   st.get("triggered_at"),
            "rules":          rules_by_entry.get(eid, []),
        })
    return result


def add_snmp_alert_rule(device_id: int, entry_id: int, operator: str,
                        threshold: str, severity: str) -> dict:
    with get_db() as db:
        db.execute(
            "INSERT INTO snmp_alerts (device_id,entry_id,operator,threshold,severity) VALUES (?,?,?,?,?)",
            (device_id, entry_id, operator, threshold, severity),
        )
        row = db.execute("SELECT * FROM snmp_alerts WHERE id=last_insert_rowid()").fetchone()
        return dict(row)


def update_snmp_alert_rule(rule_id: int, operator: str, threshold: str, severity: str):
    with get_db() as db:
        db.execute(
            "UPDATE snmp_alerts SET operator=?,threshold=?,severity=? WHERE id=?",
            (operator, threshold, severity, rule_id),
        )


def delete_snmp_alert_rule(rule_id: int):
    with get_db() as db:
        db.execute("DELETE FROM snmp_alerts WHERE id=?", (rule_id,))


def delete_entry_alerts(device_id: int, entry_id: int):
    """Delete all rules and cfg for a specific entry."""
    with get_db() as db:
        db.execute("DELETE FROM snmp_alerts WHERE device_id=? AND entry_id=?",
                   (device_id, entry_id))
        db.execute("DELETE FROM snmp_alert_entry_cfg WHERE device_id=? AND entry_id=?",
                   (device_id, entry_id))
        db.execute("DELETE FROM snmp_alert_states WHERE device_id=? AND entry_id=?",
                   (device_id, entry_id))


def set_entry_alert_enabled(device_id: int, entry_id: int, enabled: int):
    with get_db() as db:
        db.execute("""
            INSERT INTO snmp_alert_entry_cfg (device_id, entry_id, enabled)
            VALUES (?,?,?)
            ON CONFLICT(device_id, entry_id) DO UPDATE SET enabled=excluded.enabled
        """, (device_id, entry_id, enabled))


def set_alert_state(device_id: int, entry_id: int, triggered: int,
                    severity: str | None, triggered_at: str | None):
    with get_db() as db:
        db.execute("""
            INSERT INTO snmp_alert_states (device_id, entry_id, triggered, severity, triggered_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(device_id, entry_id) DO UPDATE SET
                triggered=excluded.triggered,
                severity=excluded.severity,
                triggered_at=CASE WHEN excluded.triggered=1 THEN excluded.triggered_at
                                  ELSE snmp_alert_states.triggered_at END
        """, (device_id, entry_id, triggered, severity, triggered_at))


def get_all_triggered_alerts() -> list[dict]:
    """All currently triggered, enabled-entry alerts across all devices — for dashboard widget."""
    with get_db() as db:
        rows = db.execute("""
            SELECT s.device_id, s.entry_id, s.severity AS trig_severity,
                   s.triggered_at,
                   e.label, e.oid,
                   d.name AS device_name, d.ip_address,
                   a.operator, a.threshold
            FROM snmp_alert_states s
            JOIN snmp_alert_entry_cfg cfg ON cfg.device_id=s.device_id AND cfg.entry_id=s.entry_id
            JOIN snmp_oid_entries e ON e.id=s.entry_id
            JOIN devices d ON d.id=s.device_id
            LEFT JOIN snmp_alerts a ON a.id = (
                SELECT id FROM snmp_alerts
                WHERE device_id=s.device_id AND entry_id=s.entry_id AND severity=s.severity
                LIMIT 1
            )
            WHERE s.triggered=1 AND cfg.enabled=1
            ORDER BY
                CASE s.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                s.triggered_at DESC
        """).fetchall()
        return rows_to_list(rows)


# ── User Dashboard Preferences ─────────────────────────────────

def get_user_dashboard_prefs(user_id: int) -> dict:
    with get_db() as db:
        row = db.execute(
            "SELECT prefs_json FROM user_dashboard_prefs WHERE user_id=?", (user_id,)
        ).fetchone()
    if not row:
        return {}
    try:
        return json.loads(row[0])
    except Exception:
        return {}


def set_user_dashboard_prefs(user_id: int, prefs_json: str):
    with get_db() as db:
        db.execute("""
            INSERT INTO user_dashboard_prefs (user_id, prefs_json) VALUES (?,?)
            ON CONFLICT(user_id) DO UPDATE SET prefs_json=excluded.prefs_json
        """, (user_id, prefs_json))


# ── SNMP Metrics Hidden (per user per device) ──────────────────

def get_snmp_hidden(user_id: int, device_id: int) -> list:
    with get_db() as db:
        row = db.execute(
            "SELECT hidden_ids FROM user_device_snmp_hidden WHERE user_id=? AND device_id=?",
            (user_id, device_id),
        ).fetchone()
    if not row:
        return []
    try:
        return json.loads(row[0])
    except Exception:
        return []


def set_snmp_hidden(user_id: int, device_id: int, hidden_ids: list):
    with get_db() as db:
        db.execute("""
            INSERT INTO user_device_snmp_hidden (user_id, device_id, hidden_ids)
            VALUES (?,?,?)
            ON CONFLICT(user_id, device_id) DO UPDATE SET hidden_ids=excluded.hidden_ids
        """, (user_id, device_id, json.dumps(hidden_ids)))


# ── ICMP Alert Rules ───────────────────────────────────────────

def get_icmp_alert_rules(device_id: int) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT id, device_id, operator, threshold, severity FROM icmp_alert_rules WHERE device_id=? ORDER BY id",
            (device_id,),
        ).fetchall()
        return rows_to_list(rows)


def add_icmp_alert_rule(device_id: int, operator: str, threshold: str, severity: str) -> dict:
    with get_db() as db:
        db.execute(
            "INSERT INTO icmp_alert_rules (device_id, operator, threshold, severity) VALUES (?,?,?,?)",
            (device_id, operator, threshold, severity),
        )
        row = db.execute("SELECT * FROM icmp_alert_rules WHERE id=last_insert_rowid()").fetchone()
        return row_to_dict(row)


def update_icmp_alert_rule(rule_id: int, operator: str, threshold: str, severity: str):
    with get_db() as db:
        db.execute(
            "UPDATE icmp_alert_rules SET operator=?,threshold=?,severity=? WHERE id=?",
            (operator, threshold, severity, rule_id),
        )


def delete_icmp_alert_rule(rule_id: int):
    with get_db() as db:
        db.execute("DELETE FROM icmp_alert_rules WHERE id=?", (rule_id,))


def get_icmp_alert_state(device_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM icmp_alert_states WHERE device_id=?", (device_id,)
        ).fetchone()
        return row_to_dict(row) if row else None


def set_icmp_alert_state(device_id: int, triggered: int, severity, triggered_at):
    with get_db() as db:
        db.execute("""
            INSERT INTO icmp_alert_states (device_id, triggered, severity, triggered_at)
            VALUES (?,?,?,?)
            ON CONFLICT(device_id) DO UPDATE SET
                triggered=excluded.triggered,
                severity=excluded.severity,
                triggered_at=CASE WHEN excluded.triggered=1 THEN excluded.triggered_at
                                  ELSE icmp_alert_states.triggered_at END
        """, (device_id, triggered, severity, triggered_at))


# ── URL Monitors ────────────────────────────────────────────────

def get_url_monitors(enabled_only: bool = False) -> list[dict]:
    with get_db() as db:
        if enabled_only:
            rows = db.execute(
                "SELECT * FROM url_monitors WHERE enabled=1 ORDER BY name"
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM url_monitors ORDER BY name"
            ).fetchall()
        return rows_to_list(rows)


def get_url_monitor(monitor_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM url_monitors WHERE id=?", (monitor_id,)).fetchone()
        return row_to_dict(row) if row else None


def create_url_monitor(name: str, url: str, interval_s: int = 300) -> dict:
    with get_db() as db:
        db.execute(
            "INSERT INTO url_monitors (name, url, interval_s) VALUES (?,?,?)",
            (name, url, interval_s),
        )
        row = db.execute("SELECT * FROM url_monitors WHERE id=last_insert_rowid()").fetchone()
        return row_to_dict(row)


def update_url_monitor(monitor_id: int, name: str, url: str, interval_s: int, enabled: int):
    with get_db() as db:
        db.execute(
            "UPDATE url_monitors SET name=?,url=?,interval_s=?,enabled=? WHERE id=?",
            (name, url, interval_s, enabled, monitor_id),
        )


def delete_url_monitor(monitor_id: int):
    with get_db() as db:
        db.execute("DELETE FROM url_monitors WHERE id=?", (monitor_id,))


def update_url_monitor_status(monitor_id: int, status: str, last_ip: str, checked_at: str):
    with get_db() as db:
        db.execute(
            "UPDATE url_monitors SET last_status=?,last_ip=?,last_checked=? WHERE id=?",
            (status, last_ip, checked_at, monitor_id),
        )


def add_url_monitor_result(monitor_id: int, resolved_ip: str, status: str, response_ms: float):
    with get_db() as db:
        db.execute(
            "INSERT INTO url_monitor_results (monitor_id, resolved_ip, status, response_ms) VALUES (?,?,?,?)",
            (monitor_id, resolved_ip, status, response_ms),
        )
        # Keep only last 1000 results per monitor
        db.execute("""
            DELETE FROM url_monitor_results WHERE monitor_id=? AND id NOT IN (
                SELECT id FROM url_monitor_results WHERE monitor_id=? ORDER BY id DESC LIMIT 1000
            )
        """, (monitor_id, monitor_id))


def get_url_monitor_results(monitor_id: int, limit: int = 100) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM url_monitor_results WHERE monitor_id=? ORDER BY checked_at DESC LIMIT ?",
            (monitor_id, limit),
        ).fetchall()
        return rows_to_list(rows)


# ── Widget Notification Rules ───────────────────────────────────

def get_widget_notification_rule(widget_type: str) -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM widget_notification_rules WHERE widget_type=?", (widget_type,)
        ).fetchone()
        return row_to_dict(row) if row else None


def get_all_widget_notification_rules() -> list[dict]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM widget_notification_rules").fetchall()
        return rows_to_list(rows)


def upsert_widget_notification_rule(widget_type: str, enabled: int, threshold: str,
                                    severity_filter: str, min_duration_minutes: int,
                                    message: str = "") -> dict:
    with get_db() as db:
        db.execute("""
            INSERT INTO widget_notification_rules
                (widget_type, enabled, threshold, severity_filter, min_duration_minutes, message)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(widget_type) DO UPDATE SET
                enabled=excluded.enabled,
                threshold=excluded.threshold,
                severity_filter=excluded.severity_filter,
                min_duration_minutes=excluded.min_duration_minutes,
                message=excluded.message
        """, (widget_type, enabled, threshold, severity_filter, min_duration_minutes, message))
        row = db.execute(
            "SELECT * FROM widget_notification_rules WHERE widget_type=?", (widget_type,)
        ).fetchone()
        return row_to_dict(row)


def get_widget_notification_exceptions(rule_id: int) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM widget_notification_exceptions WHERE rule_id=? ORDER BY id",
            (rule_id,),
        ).fetchall()
        return rows_to_list(rows)


def add_widget_notification_exception(rule_id: int, value: str) -> dict:
    with get_db() as db:
        db.execute(
            "INSERT INTO widget_notification_exceptions (rule_id, value) VALUES (?,?)",
            (rule_id, value),
        )
        row = db.execute(
            "SELECT * FROM widget_notification_exceptions WHERE id=last_insert_rowid()"
        ).fetchone()
        return row_to_dict(row)


def delete_widget_notification_exception(exc_id: int):
    with get_db() as db:
        db.execute("DELETE FROM widget_notification_exceptions WHERE id=?", (exc_id,))


def get_widget_notification_state(widget_type: str) -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM widget_notification_states WHERE widget_type=?", (widget_type,)
        ).fetchone()
        return row_to_dict(row) if row else None


def set_widget_notification_state(widget_type: str, is_triggered: int,
                                  first_triggered_at, last_sent_at):
    with get_db() as db:
        db.execute("""
            INSERT INTO widget_notification_states
                (widget_type, is_triggered, first_triggered_at, last_sent_at)
            VALUES (?,?,?,?)
            ON CONFLICT(widget_type) DO UPDATE SET
                is_triggered=excluded.is_triggered,
                first_triggered_at=excluded.first_triggered_at,
                last_sent_at=excluded.last_sent_at
        """, (widget_type, is_triggered, first_triggered_at, last_sent_at))


# ── Maintenance Windows ────────────────────────────────────────

def get_maintenance_windows() -> list[dict]:
    with get_db() as db:
        rows = db.execute("""
            SELECT mw.*, d.name AS device_name
            FROM maintenance_windows mw
            LEFT JOIN devices d ON mw.device_id = d.id
            ORDER BY mw.start_dt
        """).fetchall()
        return rows_to_list(rows)


def get_maintenance_window(mw_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute("""
            SELECT mw.*, d.name AS device_name
            FROM maintenance_windows mw
            LEFT JOIN devices d ON mw.device_id = d.id
            WHERE mw.id = ?
        """, (mw_id,)).fetchone()
        return row_to_dict(row) if row else None


def create_maintenance_window(name: str, device_id, start_dt: str, end_dt: str,
                               repeat_weekly: int = 0, enabled: int = 1) -> dict:
    with get_db() as db:
        db.execute("""
            INSERT INTO maintenance_windows (name, device_id, start_dt, end_dt, repeat_weekly, enabled)
            VALUES (?,?,?,?,?,?)
        """, (name, device_id, start_dt, end_dt, repeat_weekly, enabled))
        row = db.execute("""
            SELECT mw.*, d.name AS device_name
            FROM maintenance_windows mw
            LEFT JOIN devices d ON mw.device_id = d.id
            WHERE mw.id = last_insert_rowid()
        """).fetchone()
        return row_to_dict(row)


def update_maintenance_window(mw_id: int, name: str, device_id, start_dt: str,
                               end_dt: str, repeat_weekly: int = 0, enabled: int = 1) -> dict | None:
    with get_db() as db:
        db.execute("""
            UPDATE maintenance_windows
            SET name=?, device_id=?, start_dt=?, end_dt=?, repeat_weekly=?, enabled=?
            WHERE id=?
        """, (name, device_id, start_dt, end_dt, repeat_weekly, enabled, mw_id))
        row = db.execute("""
            SELECT mw.*, d.name AS device_name
            FROM maintenance_windows mw
            LEFT JOIN devices d ON mw.device_id = d.id
            WHERE mw.id = ?
        """, (mw_id,)).fetchone()
        return row_to_dict(row) if row else None


def delete_maintenance_window(mw_id: int):
    with get_db() as db:
        db.execute("DELETE FROM maintenance_windows WHERE id=?", (mw_id,))


def is_in_maintenance(device_id: int | None = None) -> bool:
    """Return True if the current UTC time is within any matching maintenance window."""
    now = datetime.utcnow()
    now_str = now.isoformat()
    with get_db() as db:
        if device_id is not None:
            rows = db.execute(
                "SELECT * FROM maintenance_windows WHERE enabled=1 AND (device_id IS NULL OR device_id=?)",
                (device_id,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM maintenance_windows WHERE enabled=1 AND device_id IS NULL"
            ).fetchall()
        for row in rows:
            mw = row_to_dict(row)
            try:
                if mw["repeat_weekly"]:
                    start = datetime.fromisoformat(mw["start_dt"])
                    end   = datetime.fromisoformat(mw["end_dt"])
                    if start.weekday() == now.weekday():
                        if start.time() <= now.time() <= end.time():
                            return True
                else:
                    if mw["start_dt"] <= now_str <= mw["end_dt"]:
                        return True
            except (ValueError, TypeError):
                continue
    return False


# ── Active Alerts (per entity) ─────────────────────────────────

def upsert_active_alert(widget_type: str, entity_id: str, entity_name: str = "") -> None:
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM active_alerts WHERE widget_type=? AND entity_id=?",
            (widget_type, entity_id),
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE active_alerts SET last_seen_at=?, entity_name=? WHERE widget_type=? AND entity_id=?",
                (now, entity_name, widget_type, entity_id),
            )
        else:
            db.execute(
                """INSERT INTO active_alerts
                   (widget_type, entity_id, entity_name, triggered_at, last_seen_at)
                   VALUES (?,?,?,?,?)""",
                (widget_type, entity_id, entity_name, now, now),
            )


def resolve_active_alert(widget_type: str, entity_id: str) -> None:
    with get_db() as db:
        db.execute(
            "DELETE FROM active_alerts WHERE widget_type=? AND entity_id=?",
            (widget_type, entity_id),
        )


def is_alert_acked(widget_type: str, entity_id: str) -> bool:
    with get_db() as db:
        row = db.execute(
            "SELECT acked FROM active_alerts WHERE widget_type=? AND entity_id=?",
            (widget_type, entity_id),
        ).fetchone()
        return bool(row and row[0])


def ack_active_alert(widget_type: str, entity_id: str,
                     acked_by: str = "admin", comment: str = "") -> bool:
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        cnt = db.execute(
            """UPDATE active_alerts
               SET acked=1, acked_by=?, acked_at=?, ack_comment=?
               WHERE widget_type=? AND entity_id=?""",
            (acked_by, now, comment, widget_type, entity_id),
        ).rowcount
        return cnt > 0


def remove_alert_ack(widget_type: str, entity_id: str) -> None:
    with get_db() as db:
        db.execute(
            """UPDATE active_alerts
               SET acked=0, acked_by='', acked_at='', ack_comment=''
               WHERE widget_type=? AND entity_id=?""",
            (widget_type, entity_id),
        )


def get_active_alerts() -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM active_alerts ORDER BY acked ASC, triggered_at DESC"
        ).fetchall()
        return rows_to_list(rows)


def get_active_alerts_by_widget(widget_type: str) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM active_alerts WHERE widget_type=? ORDER BY triggered_at DESC",
            (widget_type,),
        ).fetchall()
        return rows_to_list(rows)


def get_unacked_alert_counts() -> dict:
    with get_db() as db:
        rows = db.execute(
            "SELECT widget_type, COUNT(*) AS cnt FROM active_alerts WHERE acked=0 GROUP BY widget_type"
        ).fetchall()
        return {row[0]: row[1] for row in rows}


# ── SLA / Verfügbarkeitsberichte ───────────────────────────────

def get_device_sla(device_id: int, days: int) -> dict:
    """Compute SLA metrics for one device over the last `days` days."""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_db() as db:
        device = db.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
        if not device:
            return {}
        dev = row_to_dict(device)

        # Packet-loss based uptime
        row = db.execute("""
            SELECT
                COUNT(*)                                          AS total_checks,
                SUM(CASE WHEN value_float < 100 THEN 1 ELSE 0 END) AS online_checks,
                AVG(value_float)                                  AS avg_loss
            FROM metric_history
            WHERE device_id=? AND metric_name='icmp_packet_loss' AND timestamp >= ?
        """, (device_id, since)).fetchone()

        total   = row[0] or 0
        online  = row[1] or 0
        avg_loss = round(row[2], 1) if row[2] is not None else None

        uptime_pct = round(online / total * 100, 2) if total > 0 else None
        offline_checks = total - online
        downtime_min = round(offline_checks * dev.get("icmp_interval", 60) / 60, 1)

        # Average latency (only from successful pings)
        lat_row = db.execute("""
            SELECT AVG(value_float) FROM metric_history
            WHERE device_id=? AND metric_name='icmp_latency'
              AND value_float IS NOT NULL AND timestamp >= ?
        """, (device_id, since)).fetchone()
        avg_latency = round(lat_row[0], 1) if lat_row and lat_row[0] is not None else None

        # First and last check timestamps
        ts_row = db.execute("""
            SELECT MIN(timestamp), MAX(timestamp) FROM metric_history
            WHERE device_id=? AND metric_name='icmp_packet_loss' AND timestamp >= ?
        """, (device_id, since)).fetchone()

    return {
        "device_id":    dev["id"],
        "name":         dev["name"],
        "ip_address":   dev["ip_address"],
        "icmp_enabled": dev["icmp_enabled"],
        "total_checks": total,
        "online_checks": int(online),
        "offline_checks": int(offline_checks),
        "uptime_pct":   uptime_pct,
        "downtime_min": downtime_min,
        "avg_latency_ms": avg_latency,
        "avg_packet_loss_pct": avg_loss,
        "first_check":  ts_row[0] if ts_row else None,
        "last_check":   ts_row[1] if ts_row else None,
    }


def get_all_devices_sla(days: int) -> list[dict]:
    """SLA summary for all ICMP-enabled active devices."""
    with get_db() as db:
        rows = db.execute(
            "SELECT id FROM devices WHERE is_active=1 AND icmp_enabled=1 ORDER BY name"
        ).fetchall()
    return [get_device_sla(row[0], days) for row in rows]


def get_url_monitor_sla(monitor_id: int, days: int) -> dict:
    """SLA metrics for one URL monitor over the last `days` days."""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_db() as db:
        mon = db.execute("SELECT * FROM url_monitors WHERE id=?", (monitor_id,)).fetchone()
        if not mon:
            return {}
        m = row_to_dict(mon)

        row = db.execute("""
            SELECT
                COUNT(*)                                              AS total_checks,
                SUM(CASE WHEN status='online' THEN 1 ELSE 0 END)     AS online_checks,
                AVG(CASE WHEN status='online' THEN response_ms END)  AS avg_response_ms
            FROM url_monitor_results
            WHERE monitor_id=? AND checked_at >= ?
        """, (monitor_id, since)).fetchone()

        total   = row[0] or 0
        online  = row[1] or 0
        avg_ms  = round(row[2], 1) if row[2] is not None else None
        uptime_pct = round(online / total * 100, 2) if total > 0 else None
        offline_checks = total - online
        downtime_min = round(offline_checks * m.get("interval_s", 300) / 60, 1)

        ts_row = db.execute("""
            SELECT MIN(checked_at), MAX(checked_at) FROM url_monitor_results
            WHERE monitor_id=? AND checked_at >= ?
        """, (monitor_id, since)).fetchone()

    return {
        "monitor_id":    m["id"],
        "name":          m["name"],
        "url":           m["url"],
        "total_checks":  total,
        "online_checks": int(online),
        "offline_checks": int(offline_checks),
        "uptime_pct":    uptime_pct,
        "downtime_min":  downtime_min,
        "avg_response_ms": avg_ms,
        "first_check":   ts_row[0] if ts_row else None,
        "last_check":    ts_row[1] if ts_row else None,
    }


def get_all_url_monitors_sla(days: int) -> list[dict]:
    """SLA summary for all enabled URL monitors."""
    with get_db() as db:
        rows = db.execute(
            "SELECT id FROM url_monitors WHERE enabled=1 ORDER BY name"
        ).fetchall()
    return [get_url_monitor_sla(row[0], days) for row in rows]


# ── SNMP Traps ─────────────────────────────────────────────────

def add_snmp_trap(device_id, sender_ip: str, community: str,
                  version: str, trap_oid: str, varbinds: list) -> int:
    import json as _json
    with get_db() as db:
        db.execute(
            """INSERT INTO snmp_traps
               (device_id, sender_ip, community, version, trap_oid, varbinds_json)
               VALUES (?,?,?,?,?,?)""",
            (device_id, sender_ip, community, version, trap_oid,
             _json.dumps(varbinds, ensure_ascii=False)),
        )
        row = db.execute("SELECT last_insert_rowid()").fetchone()
        return row[0]


def get_snmp_traps(hours: int = 24, device_id: int = None,
                   limit: int = 300) -> list[dict]:
    import json as _json
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as db:
        if device_id:
            rows = db.execute(
                """SELECT t.*, d.name AS device_name
                   FROM snmp_traps t LEFT JOIN devices d ON t.device_id=d.id
                   WHERE t.device_id=? AND t.received_at >= ?
                   ORDER BY t.received_at DESC LIMIT ?""",
                (device_id, since, limit),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT t.*, d.name AS device_name
                   FROM snmp_traps t LEFT JOIN devices d ON t.device_id=d.id
                   WHERE t.received_at >= ?
                   ORDER BY t.received_at DESC LIMIT ?""",
                (since, limit),
            ).fetchall()
    result = rows_to_list(rows)
    for r in result:
        if isinstance(r.get("varbinds_json"), str):
            try:
                r["varbinds"] = _json.loads(r["varbinds_json"])
            except Exception:
                r["varbinds"] = []
    return result


def get_snmp_trap_summary(hours: int = 24) -> dict:
    """Trap count by device for the last `hours` hours."""
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as db:
        total = db.execute(
            "SELECT COUNT(*) FROM snmp_traps WHERE received_at >= ?", (since,)
        ).fetchone()[0]
        rows = db.execute(
            """SELECT COALESCE(d.name, t.sender_ip) AS label, COUNT(*) AS cnt
               FROM snmp_traps t LEFT JOIN devices d ON t.device_id=d.id
               WHERE t.received_at >= ?
               GROUP BY t.device_id, t.sender_ip
               ORDER BY cnt DESC LIMIT 20""",
            (since,),
        ).fetchall()
    return {"total": total, "by_device": [{"label": r[0], "cnt": r[1]} for r in rows]}


def prune_snmp_traps(days: int = 30):
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_db() as db:
        db.execute("DELETE FROM snmp_traps WHERE received_at < ?", (cutoff,))


# ── Widget: TCP / HTTP / SSH check status ──────────────────────

def _latest_metric(db, device_id: int, key: str):
    row = db.execute(
        "SELECT value_str, value_float, recorded_at FROM metric_history "
        "WHERE device_id=? AND metric_key=? ORDER BY id DESC LIMIT 1",
        (device_id, key),
    ).fetchone()
    return dict(row) if row else None


def get_tcp_check_status() -> list:
    with get_db() as db:
        devices = db.execute(
            "SELECT id, name, ip_address, tcp_port FROM devices "
            "WHERE tcp_enabled=1 AND is_active=1 ORDER BY name"
        ).fetchall()
        result = []
        for dev in devices:
            r = _latest_metric(db, dev["id"], "tcp_reachable")
            ms = _latest_metric(db, dev["id"], "tcp_connect_ms")
            result.append({
                "id": dev["id"], "name": dev["name"], "ip_address": dev["ip_address"],
                "port": dev["tcp_port"],
                "status": r["value_str"] if r else None,
                "connect_ms": ms["value_float"] if ms else None,
                "recorded_at": r["recorded_at"] if r else None,
            })
    return result


def get_http_check_status() -> list:
    with get_db() as db:
        devices = db.execute(
            "SELECT id, name, ip_address, http_url FROM devices "
            "WHERE http_enabled=1 AND is_active=1 ORDER BY name"
        ).fetchall()
        result = []
        for dev in devices:
            sc = _latest_metric(db, dev["id"], "http_status_code")
            ms = _latest_metric(db, dev["id"], "http_response_ms")
            result.append({
                "id": dev["id"], "name": dev["name"], "ip_address": dev["ip_address"],
                "url": dev["http_url"],
                "status_code": sc["value_str"] if sc else None,
                "response_ms": ms["value_float"] if ms else None,
                "recorded_at": sc["recorded_at"] if sc else None,
            })
    return result


def get_ssh_check_status() -> list:
    with get_db() as db:
        devices = db.execute(
            "SELECT id, name, ip_address, ssh_port FROM devices "
            "WHERE ssh_enabled=1 AND is_active=1 ORDER BY name"
        ).fetchall()
        result = []
        for dev in devices:
            r = _latest_metric(db, dev["id"], "ssh_reachable")
            ms = _latest_metric(db, dev["id"], "ssh_connect_ms")
            reachable = bool(r["value_float"]) if r else None
            banner = r["value_str"] if (r and reachable and r["value_str"] not in ("open", "closed")) else None
            result.append({
                "id": dev["id"], "name": dev["name"], "ip_address": dev["ip_address"],
                "port": dev["ssh_port"],
                "reachable": reachable,
                "banner": banner,
                "connect_ms": ms["value_float"] if ms else None,
                "recorded_at": r["recorded_at"] if r else None,
            })
    return result


# ── Widget: NetFlow Top Talkers ─────────────────────────────────

def get_netflow_top_talkers(hours: int = 24, limit: int = 10) -> dict:
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as db:
        rows = db.execute(
            """SELECT d.id, d.name, d.ip_address, SUM(m.value_float) AS total_octets
               FROM metric_history m JOIN devices d ON m.device_id=d.id
               WHERE m.metric_key='netflow_octets' AND m.recorded_at >= ?
               GROUP BY m.device_id ORDER BY total_octets DESC LIMIT ?""",
            (since, limit),
        ).fetchall()
        avg_row = db.execute(
            """SELECT AVG(total) FROM (
                 SELECT SUM(value_float) AS total FROM metric_history
                 WHERE metric_key='netflow_octets' AND recorded_at >= ?
                 GROUP BY device_id
               )""",
            (since,),
        ).fetchone()
    avg_octets = avg_row[0] if (avg_row and avg_row[0]) else 0.0
    talkers = []
    for r in rows:
        pct = round((r["total_octets"] - avg_octets) / avg_octets * 100, 1) if avg_octets > 0 else 0.0
        talkers.append({
            "id": r["id"], "name": r["name"], "ip_address": r["ip_address"],
            "total_octets": r["total_octets"], "pct_above_avg": pct,
        })
    return {"talkers": talkers, "avg_octets": round(avg_octets, 0), "hours": hours}
