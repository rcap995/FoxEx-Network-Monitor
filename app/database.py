"""sqlite3-based database layer — no SQLAlchemy required."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = "data/foxex.db"


@contextmanager
def get_db():
    """Context manager that yields a sqlite3 connection with auto-commit/rollback."""
    Path("data").mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create all tables if they do not exist."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                username         TEXT    UNIQUE NOT NULL,
                hashed_password  TEXT    NOT NULL,
                full_name        TEXT    DEFAULT '',
                role             TEXT    DEFAULT 'user',
                created_at       TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS devices (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT    NOT NULL,
                ip_address       TEXT    NOT NULL,
                device_type      TEXT    DEFAULT 'generic',
                description      TEXT    DEFAULT '',
                snmp_enabled     INTEGER DEFAULT 0,
                snmp_community   TEXT    DEFAULT 'public',
                snmp_port        INTEGER DEFAULT 161,
                icmp_enabled     INTEGER DEFAULT 1,
                icmp_interval    INTEGER DEFAULT 60,
                snmp_interval    INTEGER DEFAULT 300,
                icon_name        TEXT,
                status           TEXT    DEFAULT 'unknown',
                last_seen        TEXT,
                is_active        INTEGER DEFAULT 1,
                created_at       TEXT    DEFAULT (datetime('now')),
                -- TCP port check
                tcp_enabled      INTEGER DEFAULT 0,
                tcp_port         INTEGER DEFAULT 80,
                tcp_interval     INTEGER DEFAULT 60,
                -- HTTP/HTTPS check
                http_enabled     INTEGER DEFAULT 0,
                http_url         TEXT    DEFAULT '',
                http_interval    INTEGER DEFAULT 60,
                -- SSH banner check
                ssh_enabled      INTEGER DEFAULT 0,
                ssh_port         INTEGER DEFAULT 22,
                ssh_interval     INTEGER DEFAULT 60,
                -- WMI (Windows devices)
                wmi_enabled      INTEGER DEFAULT 0,
                wmi_username     TEXT    DEFAULT '',
                wmi_password     TEXT    DEFAULT '',
                wmi_interval     INTEGER DEFAULT 300,
                -- NetFlow / sFlow (device sends data to us)
                netflow_enabled  INTEGER DEFAULT 0,
                sflow_enabled    INTEGER DEFAULT 0,
                -- Syslog (device sends syslog messages to us)
                syslog_enabled   INTEGER DEFAULT 0,
                syslog_port      INTEGER DEFAULT 514,
                syslog_source_ip TEXT    DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS device_notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                title       TEXT    NOT NULL,
                content     TEXT    DEFAULT '',
                created_at  TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS metric_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id    INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                metric_name  TEXT    NOT NULL,
                value_float  REAL,
                value_str    TEXT,
                unit         TEXT    DEFAULT '',
                timestamp    TEXT    DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_metric_device
                ON metric_history(device_id, metric_name);
            CREATE INDEX IF NOT EXISTS idx_metric_ts
                ON metric_history(timestamp);

            CREATE TABLE IF NOT EXISTS syslog_messages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id    INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                facility     INTEGER DEFAULT 1,
                severity     INTEGER DEFAULT 6,
                severity_name TEXT   DEFAULT 'info',
                hostname     TEXT   DEFAULT '',
                message      TEXT   DEFAULT '',
                raw          TEXT   DEFAULT '',
                received_at  TEXT   DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_syslog_device
                ON syslog_messages(device_id, received_at);
        """)
        # Migration: add new columns to existing databases (ignore if already exist)
        new_cols = [
            ("tcp_enabled",     "INTEGER DEFAULT 0"),
            ("tcp_port",        "INTEGER DEFAULT 80"),
            ("tcp_interval",    "INTEGER DEFAULT 60"),
            ("http_enabled",    "INTEGER DEFAULT 0"),
            ("http_url",        "TEXT DEFAULT ''"),
            ("http_interval",   "INTEGER DEFAULT 60"),
            ("ssh_enabled",     "INTEGER DEFAULT 0"),
            ("ssh_port",        "INTEGER DEFAULT 22"),
            ("ssh_interval",    "INTEGER DEFAULT 60"),
            ("wmi_enabled",     "INTEGER DEFAULT 0"),
            ("wmi_username",    "TEXT DEFAULT ''"),
            ("wmi_password",    "TEXT DEFAULT ''"),
            ("wmi_interval",    "INTEGER DEFAULT 300"),
            ("netflow_enabled",         "INTEGER DEFAULT 0"),
            ("sflow_enabled",          "INTEGER DEFAULT 0"),
            ("snmp_metrics_disabled",  "TEXT DEFAULT '[]'"),
            ("syslog_enabled",         "INTEGER DEFAULT 0"),
            ("syslog_port",            "INTEGER DEFAULT 514"),
            ("syslog_source_ip",       "TEXT DEFAULT ''"),
        ]
        user_cols = [
            ("full_name",       "TEXT DEFAULT ''"),
            ("role",            "TEXT DEFAULT 'user'"),
            ("force_pw_change", "INTEGER DEFAULT 0"),
        ]
        for col, col_def in user_cols:
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_def}")
                conn.commit()
            except Exception:
                pass
        # Make the first user (id=1) an admin if role column was just added
        try:
            conn.execute("UPDATE users SET role='admin' WHERE id=1 AND role='user'")
            conn.commit()
        except Exception:
            pass
        for col, col_def in new_cols:
            try:
                conn.execute(f"ALTER TABLE devices ADD COLUMN {col} {col_def}")
                conn.commit()
            except Exception:
                pass  # column already exists
        conn.executescript("""

            CREATE TABLE IF NOT EXISTS topology_maps (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT DEFAULT 'default',
                data_json   TEXT DEFAULT '{"nodes":[],"edges":[]}',
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key   TEXT PRIMARY KEY,
                value TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS snmp_oid_templates (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                is_default  INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS snmp_oid_entries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER NOT NULL REFERENCES snmp_oid_templates(id) ON DELETE CASCADE,
                oid         TEXT NOT NULL,
                label       TEXT NOT NULL,
                unit        TEXT DEFAULT ''
            );
        """)
        # Migrate new device columns
        new_device_cols = [
            ("snmp_template_id",   "INTEGER DEFAULT NULL"),
            ("snmp_v3_username",   "TEXT DEFAULT ''"),
            ("snmp_v3_auth_proto", "TEXT DEFAULT 'SHA'"),
            ("snmp_v3_auth_pass",  "TEXT DEFAULT ''"),
            ("snmp_v3_priv_proto", "TEXT DEFAULT 'AES'"),
            ("snmp_v3_priv_pass",  "TEXT DEFAULT ''"),
        ]
        for col, col_def in new_device_cols:
            try:
                conn.execute(f"ALTER TABLE devices ADD COLUMN {col} {col_def}")
                conn.commit()
            except Exception:
                pass

        # Migrate snmp_oid_templates: add is_default column
        try:
            conn.execute("ALTER TABLE snmp_oid_templates ADD COLUMN is_default INTEGER DEFAULT 0")
            conn.commit()
        except Exception:
            pass  # column already exists

        # Seed default OID template (once, idempotent)
        existing = conn.execute(
            "SELECT id FROM snmp_oid_templates WHERE is_default=1"
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO snmp_oid_templates (name, description, is_default) "
                "VALUES (?, ?, 1)",
                ("Standard (System)", "Vordefiniertes Template mit Standard-System-OIDs"),
            )
            conn.commit()
            tid = conn.execute(
                "SELECT id FROM snmp_oid_templates WHERE is_default=1"
            ).fetchone()[0]
            _DEFAULT_ENTRIES = [
                ("1.3.6.1.2.1.1.5.0",           "System Name",                    ""),
                ("1.3.6.1.2.1.1.3.0",           "System Uptime",                  "timeticks"),
                ("1.3.6.1.2.1.25.3.3.1.2",      "CPU Auslastung",                 "%"),
                ("1.3.6.1.2.1.25.2.2.0",        "Arbeitsspeicher gesamt",         "KB"),
                ("1.3.6.1.2.1.25.2.3.1.6",      "Speicher belegt (Einheiten)",    ""),
                ("1.3.6.1.2.1.2.2.1.8",         "Interface Status",               ""),
                ("1.3.6.1.2.1.2.2.1.10",        "Eingehender Datenverkehr",       "bytes"),
                ("1.3.6.1.2.1.2.2.1.16",        "Ausgehender Datenverkehr",       "bytes"),
                ("1.3.6.1.2.1.2.2.1.2",         "Interface Bezeichnung",          ""),
                ("1.3.6.1.2.1.25.2.3.1.3",      "Speicher Bezeichnung",           ""),
                ("1.3.6.1.2.1.25.2.3.1.4",      "Speicher Einheitengröße",        "bytes"),
                ("1.3.6.1.2.1.25.2.3.1.5",      "Speicher Gesamtgröße (Einh.)",   ""),
            ]
            for oid, label, unit in _DEFAULT_ENTRIES:
                conn.execute(
                    "INSERT INTO snmp_oid_entries (template_id, oid, label, unit) VALUES (?,?,?,?)",
                    (tid, oid, label, unit),
                )
            conn.commit()

        # Junction table: device ↔ SNMP templates (many-to-many)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS device_snmp_templates (
                device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                template_id INTEGER NOT NULL REFERENCES snmp_oid_templates(id) ON DELETE CASCADE,
                PRIMARY KEY (device_id, template_id)
            );
        """)
        # Migrate existing single snmp_template_id → junction table
        try:
            conn.execute("""
                INSERT OR IGNORE INTO device_snmp_templates (device_id, template_id)
                SELECT id, snmp_template_id FROM devices WHERE snmp_template_id IS NOT NULL
            """)
            conn.commit()
        except Exception:
            pass

        # ── Alert tables ───────────────────────────────────────────
        # snmp_alerts: one row per rule (multiple rules per entry allowed)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS snmp_alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                entry_id    INTEGER NOT NULL REFERENCES snmp_oid_entries(id) ON DELETE CASCADE,
                operator    TEXT    NOT NULL DEFAULT '>',
                threshold   TEXT    NOT NULL DEFAULT '',
                severity    TEXT    NOT NULL DEFAULT 'warning'
            );
            CREATE TABLE IF NOT EXISTS snmp_alert_entry_cfg (
                device_id   INTEGER NOT NULL,
                entry_id    INTEGER NOT NULL,
                enabled     INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (device_id, entry_id)
            );
            CREATE TABLE IF NOT EXISTS snmp_alert_states (
                device_id    INTEGER NOT NULL,
                entry_id     INTEGER NOT NULL,
                triggered    INTEGER NOT NULL DEFAULT 0,
                severity     TEXT,
                triggered_at TEXT,
                PRIMARY KEY (device_id, entry_id)
            );
            CREATE TABLE IF NOT EXISTS user_dashboard_prefs (
                user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                prefs_json TEXT    NOT NULL DEFAULT '{}'
            );
        """)
        # Migrate old snmp_alerts if it had UNIQUE constraint (from previous version)
        try:
            schema = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='snmp_alerts'"
            ).fetchone()
            if schema and schema[0] and 'UNIQUE' in schema[0]:
                old_rows = conn.execute(
                    "SELECT device_id, entry_id, operator, threshold, severity, "
                    "COALESCE(enabled,1) FROM snmp_alerts"
                ).fetchall()
                conn.execute("DROP TABLE snmp_alerts")
                conn.execute("""
                    CREATE TABLE snmp_alerts (
                        id        INTEGER PRIMARY KEY AUTOINCREMENT,
                        device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                        entry_id  INTEGER NOT NULL REFERENCES snmp_oid_entries(id) ON DELETE CASCADE,
                        operator  TEXT    NOT NULL DEFAULT '>',
                        threshold TEXT    NOT NULL DEFAULT '',
                        severity  TEXT    NOT NULL DEFAULT 'warning'
                    )""")
                for row in old_rows:
                    conn.execute(
                        "INSERT INTO snmp_alerts (device_id,entry_id,operator,threshold,severity) VALUES (?,?,?,?,?)",
                        (row[0], row[1], row[2], row[3], row[4]),
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO snmp_alert_entry_cfg (device_id,entry_id,enabled) VALUES (?,?,?)",
                        (row[0], row[1], row[5]),
                    )
                conn.commit()
        except Exception:
            pass
        # Migrate snmp_alert_states: add severity column if missing
        try:
            conn.execute("ALTER TABLE snmp_alert_states ADD COLUMN severity TEXT")
            conn.commit()
        except Exception:
            pass

        # ── sort_order on snmp_oid_entries ─────────────────────────
        try:
            conn.execute("ALTER TABLE snmp_oid_entries ADD COLUMN sort_order INTEGER DEFAULT 0")
            conn.commit()
        except Exception:
            pass
        # Initialise sort_order for existing entries (only those still at 0)
        try:
            # Set sort_order = rownum ordered by id for each template
            tids = [r[0] for r in conn.execute(
                "SELECT DISTINCT template_id FROM snmp_oid_entries"
            ).fetchall()]
            for tid in tids:
                rows = conn.execute(
                    "SELECT id FROM snmp_oid_entries WHERE template_id=? ORDER BY id",
                    (tid,),
                ).fetchall()
                for pos, row in enumerate(rows):
                    conn.execute(
                        "UPDATE snmp_oid_entries SET sort_order=? WHERE id=?",
                        (pos, row[0]),
                    )
            conn.commit()
        except Exception:
            pass
        # For the default template: move sysDescr/sysContact/sysLocation to top
        try:
            default_row = conn.execute(
                "SELECT id FROM snmp_oid_templates WHERE is_default=1"
            ).fetchone()
            if default_row:
                dtid = default_row[0]
                _top_oids = [
                    "1.3.6.1.2.1.1.1.0",  # sysDescr
                    "1.3.6.1.2.1.1.4.0",  # sysContact
                    "1.3.6.1.2.1.1.6.0",  # sysLocation
                ]
                # Get all entries for this template ordered by current sort_order
                all_entries = conn.execute(
                    "SELECT id, oid FROM snmp_oid_entries WHERE template_id=? ORDER BY sort_order",
                    (dtid,),
                ).fetchall()
                top_ids    = [r[0] for r in all_entries if r[1] in _top_oids]
                other_ids  = [r[0] for r in all_entries if r[1] not in _top_oids]
                for pos, eid in enumerate(top_ids + other_ids):
                    conn.execute(
                        "UPDATE snmp_oid_entries SET sort_order=? WHERE id=?",
                        (pos, eid),
                    )
                conn.commit()
        except Exception:
            pass

        # Add sysDescr, sysContact, sysLocation to default template if missing
        try:
            default_row = conn.execute(
                "SELECT id FROM snmp_oid_templates WHERE is_default=1"
            ).fetchone()
            if default_row:
                dtid = default_row[0]
                _extra_oids = [
                    ("1.3.6.1.2.1.1.1.0", "System Beschreibung", ""),
                    ("1.3.6.1.2.1.1.4.0", "System Kontakt",      ""),
                    ("1.3.6.1.2.1.1.6.0", "System Standort",     ""),
                ]
                for oid, label, unit in _extra_oids:
                    exists = conn.execute(
                        "SELECT 1 FROM snmp_oid_entries WHERE template_id=? AND oid=?",
                        (dtid, oid)
                    ).fetchone()
                    if not exists:
                        conn.execute(
                            "INSERT INTO snmp_oid_entries (template_id, oid, label, unit) VALUES (?,?,?,?)",
                            (dtid, oid, label, unit),
                        )
            conn.commit()
        except Exception:
            pass

        # ── ICMP alert rules & states ───────────────────────────────
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS icmp_alert_rules (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                operator    TEXT    NOT NULL DEFAULT '>',
                threshold   TEXT    NOT NULL DEFAULT '',
                severity    TEXT    NOT NULL DEFAULT 'warning'
            );
            CREATE TABLE IF NOT EXISTS icmp_alert_states (
                device_id    INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
                triggered    INTEGER NOT NULL DEFAULT 0,
                severity     TEXT,
                triggered_at TEXT
            );
        """)

        # ── SNMP hidden metrics per user per device ─────────────────
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS user_device_snmp_hidden (
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                device_id  INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                hidden_ids TEXT    NOT NULL DEFAULT '[]',
                PRIMARY KEY (user_id, device_id)
            );
        """)

        # ── URL Monitors (DNS checks) ────────────────────────────────
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS url_monitors (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT    NOT NULL,
                url          TEXT    NOT NULL,
                interval_s   INTEGER DEFAULT 300,
                enabled      INTEGER DEFAULT 1,
                last_checked TEXT,
                last_status  TEXT    DEFAULT 'unknown',
                last_ip      TEXT    DEFAULT '',
                created_at   TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS url_monitor_results (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor_id  INTEGER NOT NULL REFERENCES url_monitors(id) ON DELETE CASCADE,
                checked_at  TEXT    DEFAULT (datetime('now')),
                resolved_ip TEXT    DEFAULT '',
                status      TEXT    DEFAULT 'unknown',
                response_ms REAL
            );
            CREATE INDEX IF NOT EXISTS idx_url_results_monitor
                ON url_monitor_results(monitor_id, checked_at);

            -- Widget notification rules (one row per widget type)
            CREATE TABLE IF NOT EXISTS widget_notification_rules (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                widget_type          TEXT    NOT NULL UNIQUE,
                enabled              INTEGER DEFAULT 0,
                threshold            TEXT    DEFAULT '',
                severity_filter      TEXT    DEFAULT '',
                min_duration_minutes INTEGER DEFAULT 0,
                message              TEXT    DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS widget_notification_exceptions (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id  INTEGER NOT NULL REFERENCES widget_notification_rules(id) ON DELETE CASCADE,
                value    TEXT    NOT NULL
            );

            -- Tracks debounce state per widget type
            CREATE TABLE IF NOT EXISTS widget_notification_states (
                widget_type        TEXT PRIMARY KEY,
                first_triggered_at TEXT,
                last_sent_at       TEXT,
                is_triggered       INTEGER DEFAULT 0
            );

            -- ── Maintenance Windows ────────────────────────────────────
            CREATE TABLE IF NOT EXISTS maintenance_windows (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL DEFAULT 'Wartungsfenster',
                device_id     INTEGER REFERENCES devices(id) ON DELETE CASCADE,
                start_dt      TEXT    NOT NULL,
                end_dt        TEXT    NOT NULL,
                repeat_weekly INTEGER DEFAULT 0,
                enabled       INTEGER DEFAULT 1,
                created_at    TEXT    DEFAULT (datetime('now'))
            );

            -- ── Active Alerts (per entity, used for acknowledgment) ────
            CREATE TABLE IF NOT EXISTS active_alerts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                widget_type  TEXT    NOT NULL,
                entity_id    TEXT    NOT NULL,
                entity_name  TEXT    DEFAULT '',
                triggered_at TEXT    DEFAULT (datetime('now')),
                last_seen_at TEXT    DEFAULT (datetime('now')),
                acked        INTEGER DEFAULT 0,
                acked_by     TEXT    DEFAULT '',
                acked_at     TEXT    DEFAULT '',
                ack_comment  TEXT    DEFAULT '',
                UNIQUE(widget_type, entity_id)
            );
        """)
        # Migration: add message column if not present (existing databases)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(widget_notification_rules)").fetchall()]
        if "message" not in cols:
            conn.execute("ALTER TABLE widget_notification_rules ADD COLUMN message TEXT DEFAULT ''")

        # ── SNMP Traps ──────────────────────────────────────────────
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS snmp_traps (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id     INTEGER REFERENCES devices(id) ON DELETE SET NULL,
                sender_ip     TEXT    NOT NULL DEFAULT '',
                community     TEXT    DEFAULT '',
                version       TEXT    DEFAULT 'v2c',
                trap_oid      TEXT    DEFAULT '',
                varbinds_json TEXT    DEFAULT '[]',
                received_at   TEXT    DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_snmp_traps_ts
                ON snmp_traps(received_at);
            CREATE INDEX IF NOT EXISTS idx_snmp_traps_device
                ON snmp_traps(device_id, received_at);
        """)

        # ── SSH Service Monitors ────────────────────────────────────
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ssh_service_monitors (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                name                 TEXT    NOT NULL,
                host                 TEXT    NOT NULL,
                port                 INTEGER DEFAULT 22,
                username             TEXT    NOT NULL DEFAULT '',
                password             TEXT    DEFAULT '',
                service_name         TEXT    NOT NULL,
                check_interval       INTEGER DEFAULT 60,
                enabled              INTEGER DEFAULT 1,
                last_status          TEXT    DEFAULT 'unknown',
                last_output          TEXT    DEFAULT '',
                last_check           TEXT,
                consecutive_failures INTEGER DEFAULT 0,
                created_at           TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS ssh_service_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor_id  INTEGER NOT NULL REFERENCES ssh_service_monitors(id) ON DELETE CASCADE,
                timestamp   TEXT    DEFAULT (datetime('now')),
                status      TEXT    NOT NULL,
                output      TEXT    DEFAULT '',
                response_ms REAL
            );
            CREATE INDEX IF NOT EXISTS idx_ssh_svc_hist
                ON ssh_service_history(monitor_id, timestamp);
        """)
