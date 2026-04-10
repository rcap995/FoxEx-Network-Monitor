"""System + app settings and SNMP OID template routes."""
import re
import socket
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException
from app import crud

router = APIRouter()


def _require_login(request: Request) -> dict:
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401)
    user = crud.get_user(uid)
    if not user:
        raise HTTPException(status_code=401)
    return user


def _require_admin(request: Request) -> dict:
    user = _require_login(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator erforderlich")
    return user


def _sudo(cmd: list, input_data: bytes | None = None) -> tuple[bool, str]:
    """Attempt a sudo -n command. Returns (success, message)."""
    try:
        r = subprocess.run(
            ["sudo", "-n"] + cmd,
            capture_output=True, timeout=10, input=input_data,
        )
        if r.returncode == 0:
            return True, r.stdout.decode(errors="replace").strip() or "OK"
        err = r.stderr.decode(errors="replace").strip()
        if "password is required" in err or "no passwd" in err.lower():
            return False, (
                "Hinweis: sudoers nicht konfiguriert. "
                "Führe auf dem Server aus: "
                "echo 'YOUR_USER ALL=(ALL) NOPASSWD: /usr/bin/hostnamectl,"
                "/usr/bin/tee,/usr/bin/systemctl,/usr/bin/timedatectl' "
                "| sudo tee /etc/sudoers.d/foxex-monitor"
            )
        return False, err or "Unbekannter Fehler"
    except subprocess.TimeoutExpired:
        return False, "Timeout beim Ausführen des Befehls"
    except Exception as exc:
        return False, str(exc)


# ── System Info ────────────────────────────────────────────────

@router.get("/api/settings/system")
def api_system_info(request: Request):
    _require_admin(request)

    hostname = socket.gethostname()

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "127.0.0.1"

    sys_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    ntp_server = ""
    try:
        content = Path("/etc/systemd/timesyncd.conf").read_text()
        m = re.search(r"^NTP\s*=\s*(.+)$", content, re.MULTILINE)
        if m:
            ntp_server = m.group(1).strip()
    except Exception:
        pass
    if not ntp_server:
        ntp_server = crud.get_setting("system.ntp_server", "")

    dns_servers = ""
    try:
        lines = Path("/etc/resolv.conf").read_text().splitlines()
        dns_servers = ", ".join(l.split()[1] for l in lines if l.startswith("nameserver"))
    except Exception:
        dns_servers = crud.get_setting("system.dns_servers", "")

    gateway = ""
    try:
        r = subprocess.run(["ip", "route", "show", "default"],
                           capture_output=True, timeout=5, text=True)
        m = re.search(r"default via (\S+)", r.stdout)
        if m:
            gateway = m.group(1)
    except Exception:
        pass

    netmask = ""
    try:
        r = subprocess.run(["ip", "-o", "-f", "inet", "addr", "show"],
                           capture_output=True, timeout=5, text=True)
        for line in r.stdout.splitlines():
            if ip in line:
                m = re.search(r"inet (\S+)", line)
                if m:
                    netmask = m.group(1)  # CIDR notation e.g. 192.168.1.1/24
    except Exception:
        pass

    app_port = crud.get_setting("system.port", "8000")

    return {
        "hostname":   hostname,
        "ip_address": ip,
        "netmask":    netmask,
        "gateway":    gateway,
        "dns_servers": dns_servers,
        "ntp_server":  ntp_server,
        "system_time": sys_time,
        "app_port":    app_port,
    }


@router.post("/api/settings/system/hostname")
async def api_set_hostname(request: Request):
    _require_admin(request)
    body = await request.json()
    name = body.get("hostname", "").strip()
    if not name or not re.match(r"^[a-zA-Z0-9\-]{1,63}$", name):
        raise HTTPException(status_code=400, detail="Ungültiger Hostname (nur Buchstaben, Zahlen, Bindestriche)")
    ok, msg = _sudo(["hostnamectl", "set-hostname", name])
    return {"ok": ok, "message": msg}


@router.post("/api/settings/system/ntp")
async def api_set_ntp(request: Request):
    _require_admin(request)
    body = await request.json()
    server = body.get("ntp_server", "").strip()
    crud.set_setting("system.ntp_server", server)
    if not server:
        return {"ok": True, "message": "NTP-Server entfernt (in App gespeichert)"}
    conf = f"[Time]\nNTP={server}\n"
    ok, _ = _sudo(["tee", "/etc/systemd/timesyncd.conf"], input_data=conf.encode())
    if ok:
        ok2, msg = _sudo(["systemctl", "restart", "systemd-timesyncd"])
        return {"ok": ok2, "message": msg or f"NTP-Server {server} konfiguriert"}
    return {"ok": True, "message": f"In App gespeichert. Systemänderung erfordert sudoers-Konfiguration."}


@router.post("/api/settings/system/dns")
async def api_set_dns(request: Request):
    _require_admin(request)
    body = await request.json()
    servers = body.get("dns_servers", "").strip()
    crud.set_setting("system.dns_servers", servers)
    if not servers:
        return {"ok": True, "message": "DNS in App gespeichert"}
    lines = "\n".join(f"nameserver {s.strip()}" for s in servers.split(",") if s.strip())
    ok, msg = _sudo(["tee", "/etc/resolv.conf"], input_data=(lines + "\n").encode())
    if ok:
        return {"ok": True, "message": "DNS-Server aktualisiert"}
    return {"ok": True, "message": "In App gespeichert. Systemänderung erfordert sudoers-Konfiguration."}


@router.post("/api/settings/system/port")
async def api_set_port(request: Request):
    _require_admin(request)
    body = await request.json()
    try:
        port = int(body.get("port", 8000))
        if not (1024 <= port <= 65535):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Ungültiger Port (1024–65535)")
    crud.set_setting("system.port", str(port))
    return {"ok": True, "message": f"Port {port} gespeichert. Dienst-Neustart erforderlich."}


# ── App Settings (protocols, RADIUS) ──────────────────────────

@router.get("/api/settings")
def api_get_settings(request: Request):
    _require_admin(request)
    return crud.get_all_settings()


@router.post("/api/settings")
async def api_save_settings(request: Request):
    _require_admin(request)
    body = await request.json()
    allowed = {
        "icmp.packet_size", "icmp.count", "icmp.timeout",
        "dns.interval",
        "snmp.v2_community", "snmp.v2_port",
        "snmp.v3_username", "snmp.v3_auth_proto", "snmp.v3_auth_pass",
        "snmp.v3_priv_proto", "snmp.v3_priv_pass",
        "radius.enabled", "radius.server", "radius.port",
        "radius.secret", "radius.timeout",
        "syslog.retention.emerg", "syslog.retention.alert",
        "syslog.retention.crit",  "syslog.retention.err",
        "syslog.retention.warning", "syslog.retention.notice",
        "syslog.retention.info",  "syslog.retention.debug",
        "mail.notify.enabled",   "mail.notify.smtp_host", "mail.notify.smtp_port",
        "mail.notify.encryption","mail.notify.username",  "mail.notify.password",
        "mail.notify.from",      "mail.notify.to",
        "mail.notify.on_offline","mail.notify.on_icmp",
        "mail.notify.on_snmp",   "mail.notify.on_syslog",
    }
    for k, v in body.items():
        if k in allowed:
            crud.set_setting(k, str(v))
    return {"ok": True}


@router.post("/api/settings/email/test")
async def api_test_email(request: Request):
    """Send a test e-mail using the stored SMTP settings."""
    import smtplib, ssl as _ssl
    from email.message import EmailMessage

    _require_admin(request)

    host = crud.get_setting("mail.notify.smtp_host", "").strip()
    port = int(crud.get_setting("mail.notify.smtp_port", "587") or 587)
    enc  = crud.get_setting("mail.notify.encryption", "starttls").strip()
    user = crud.get_setting("mail.notify.username", "").strip()
    pwd  = crud.get_setting("mail.notify.password", "")
    from_addr = crud.get_setting("mail.notify.from", "").strip() or user
    to_addr   = crud.get_setting("mail.notify.to",   "").strip()

    if not host:
        raise HTTPException(status_code=400, detail="SMTP-Host nicht konfiguriert")
    if not to_addr:
        raise HTTPException(status_code=400, detail="Empfänger-Adresse nicht konfiguriert")

    msg = EmailMessage()
    msg["Subject"] = "FoxEx Network Monitor – Test-E-Mail"
    msg["From"]    = from_addr
    msg["To"]      = to_addr
    msg.set_content(
        "Dies ist eine Test-E-Mail vom FoxEx Network Monitor.\n\n"
        "Wenn Sie diese Nachricht erhalten, ist die E-Mail-Konfiguration korrekt."
    )

    try:
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
        return {"ok": True, "message": f"Test-E-Mail an {to_addr} gesendet"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── SNMP OID Templates ─────────────────────────────────────────

@router.get("/api/snmp/templates")
def api_list_templates(request: Request):
    """All logged-in users can list templates (for device form dropdowns).
    Admins additionally receive the OID entries."""
    user = _require_login(request)
    templates = crud.get_snmp_templates()
    if user.get("role") == "admin":
        for t in templates:
            t["entries"] = crud.get_template_entries(t["id"])
    return templates


@router.post("/api/snmp/templates")
async def api_create_template(request: Request):
    _require_admin(request)
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name erforderlich")
    return crud.create_snmp_template(name, body.get("description", "").strip())


@router.put("/api/snmp/templates/{tid}")
async def api_update_template(tid: int, request: Request):
    _require_admin(request)
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name erforderlich")
    crud.update_snmp_template(tid, name, body.get("description", ""))
    return {"ok": True}


@router.delete("/api/snmp/templates/{tid}")
def api_delete_template(tid: int, request: Request):
    _require_admin(request)
    tpl = crud.get_snmp_template(tid)
    if not tpl:
        raise HTTPException(status_code=404)
    if tpl.get("is_default"):
        raise HTTPException(status_code=403, detail="Standard-Template kann nicht gelöscht werden")
    crud.delete_snmp_template(tid)
    return {"ok": True}


@router.get("/api/snmp/templates/{tid}/entries")
def api_get_entries(tid: int, request: Request):
    _require_login(request)
    return crud.get_template_entries(tid)


@router.post("/api/snmp/templates/{tid}/entries")
async def api_add_entry(tid: int, request: Request):
    _require_admin(request)
    if not crud.get_snmp_template(tid):
        raise HTTPException(status_code=404, detail="Template nicht gefunden")
    body = await request.json()
    oid   = body.get("oid", "").strip()
    label = body.get("label", "").strip()
    unit  = body.get("unit", "").strip()
    if not oid or not label:
        raise HTTPException(status_code=400, detail="OID und Bezeichnung erforderlich")
    return crud.add_template_entry(tid, oid, label, unit)


@router.delete("/api/snmp/templates/{tid}/entries/{eid}")
def api_delete_entry(tid: int, eid: int, request: Request):
    _require_admin(request)
    crud.delete_template_entry(eid)
    return {"ok": True}


@router.put("/api/snmp/templates/{tid}/entries/sort-order")
async def api_set_sort_order(tid: int, request: Request):
    _require_login(request)
    body = await request.json()
    ordered_ids = [int(x) for x in body.get("order", [])]
    crud.set_entry_sort_orders(tid, ordered_ids)
    return {"ok": True}
