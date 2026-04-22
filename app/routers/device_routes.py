import shutil
from pathlib import Path

from fastapi import APIRouter, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from app.templates_config import templates

from app import crud
from app.auth import require_operator, _get_session_user, _ROLE_RANK
from app.config import DEVICE_TYPES, UPLOAD_DIR
from app.monitoring.scheduler import schedule_device, unschedule_device, run_device_check
from app.monitoring.http_check import http_check
from app.monitoring.tcp_check import tcp_check
from app.monitoring.ssh_check import ssh_check

router = APIRouter()
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


def _check(request: Request):
    if not request.session.get("user_id"):
        raise HTTPException(status_code=302, headers={"Location": "/login"})


# ── Pages ─────────────────────────────────────────────────────

@router.get("/devices", response_class=HTMLResponse)
def devices_page(request: Request):
    _check(request)
    return templates.TemplateResponse("devices.html", {
        "request": request,
        "devices": crud.get_all_devices(),
        "device_types": DEVICE_TYPES,
        "username": request.session.get("username"),
    })


@router.get("/devices/{device_id}", response_class=HTMLResponse)
def device_detail_page(device_id: int, request: Request):
    _check(request)
    device = crud.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404)
    recent_icmp = crud.get_metrics(device_id, "icmp_latency", hours=24, limit=100)
    latest_metrics = crud.get_latest_metrics(device_id)
    template_ids = crud.get_device_template_ids(device_id)
    user = _get_session_user(request)
    return templates.TemplateResponse("device_detail.html", {
        "request": request,
        "device": device,
        "device_types": DEVICE_TYPES,
        "recent_icmp": recent_icmp,
        "latest_metrics": latest_metrics,
        "username": request.session.get("username"),
        "template_ids": template_ids,
        "user_role": user.get("role", "user"),
    })


# ── API: Devices ──────────────────────────────────────────────

@router.get("/api/devices")
def api_list_devices(request: Request):
    _check(request)
    devices = crud.get_all_devices()
    return [
        {
            "id": d["id"], "name": d["name"], "ip_address": d["ip_address"],
            "device_type": d["device_type"], "status": d["status"],
            "icon_name": d["icon_name"], "is_active": bool(d["is_active"]),
            "last_seen": d["last_seen"],
        }
        for d in devices
    ]


@router.post("/api/devices")
def api_create_device(
    request: Request,
    name: str = Form(...),
    ip_address: str = Form(...),
    device_type: str = Form("generic"),
    description: str = Form(""),
    snmp_enabled: str = Form("false"),
    snmp_community: str = Form("public"),
    snmp_port: int = Form(161),
    icmp_enabled: str = Form("true"),
    icmp_interval: int = Form(60),
    snmp_interval: int = Form(300),
    tcp_enabled: str = Form("false"),
    tcp_port: int = Form(80),
    tcp_interval: int = Form(60),
    http_enabled: str = Form("false"),
    http_url: str = Form(""),
    http_interval: int = Form(60),
    ssh_enabled: str = Form("false"),
    ssh_port: int = Form(22),
    ssh_interval: int = Form(60),
    wmi_enabled: str = Form("false"),
    wmi_username: str = Form(""),
    wmi_password: str = Form(""),
    wmi_interval: int = Form(300),
    netflow_enabled: str = Form("false"),
    sflow_enabled: str = Form("false"),
    syslog_enabled: str = Form("false"),
    syslog_port: int = Form(514),
    syslog_source_ip: str = Form(""),
    snmp_template_ids: str = Form(""),
):
    require_operator(request)
    device = crud.create_device({
        "name": name, "ip_address": ip_address, "device_type": device_type,
        "description": description,
        "snmp_enabled": snmp_enabled.lower() == "true",
        "snmp_community": snmp_community, "snmp_port": snmp_port,
        "icmp_enabled": icmp_enabled.lower() == "true",
        "icmp_interval": icmp_interval, "snmp_interval": snmp_interval,
        "tcp_enabled": tcp_enabled.lower() == "true",
        "tcp_port": tcp_port, "tcp_interval": tcp_interval,
        "http_enabled": http_enabled.lower() == "true",
        "http_url": http_url, "http_interval": http_interval,
        "ssh_enabled": ssh_enabled.lower() == "true",
        "ssh_port": ssh_port, "ssh_interval": ssh_interval,
        "wmi_enabled": wmi_enabled.lower() == "true",
        "wmi_username": wmi_username, "wmi_password": wmi_password,
        "wmi_interval": wmi_interval,
        "netflow_enabled": netflow_enabled.lower() == "true",
        "sflow_enabled": sflow_enabled.lower() == "true",
        "syslog_enabled": syslog_enabled.lower() == "true",
        "syslog_port": syslog_port,
        "syslog_source_ip": syslog_source_ip,
    })
    schedule_device(device)
    _ids = [int(x) for x in snmp_template_ids.split(",") if x.strip()]
    crud.set_device_templates(device["id"], _ids)
    return {"id": device["id"], "name": device["name"]}


@router.put("/api/devices/{device_id}")
def api_update_device(
    device_id: int,
    request: Request,
    name: str = Form(...),
    ip_address: str = Form(...),
    device_type: str = Form("generic"),
    description: str = Form(""),
    snmp_enabled: str = Form("false"),
    snmp_community: str = Form("public"),
    snmp_port: int = Form(161),
    icmp_enabled: str = Form("true"),
    icmp_interval: int = Form(60),
    snmp_interval: int = Form(300),
    tcp_enabled: str = Form("false"),
    tcp_port: int = Form(80),
    tcp_interval: int = Form(60),
    http_enabled: str = Form("false"),
    http_url: str = Form(""),
    http_interval: int = Form(60),
    ssh_enabled: str = Form("false"),
    ssh_port: int = Form(22),
    ssh_interval: int = Form(60),
    wmi_enabled: str = Form("false"),
    wmi_username: str = Form(""),
    wmi_password: str = Form(""),
    wmi_interval: int = Form(300),
    netflow_enabled: str = Form("false"),
    sflow_enabled: str = Form("false"),
    syslog_enabled: str = Form("false"),
    syslog_port: int = Form(514),
    syslog_source_ip: str = Form(""),
    snmp_template_ids: str = Form(""),
    is_active: str = Form("true"),
):
    _check(request)
    if not crud.get_device(device_id):
        raise HTTPException(status_code=404)
    device = crud.update_device(device_id, {
        "name": name, "ip_address": ip_address, "device_type": device_type,
        "description": description,
        "snmp_enabled": snmp_enabled.lower() == "true",
        "snmp_community": snmp_community, "snmp_port": snmp_port,
        "icmp_enabled": icmp_enabled.lower() == "true",
        "icmp_interval": icmp_interval, "snmp_interval": snmp_interval,
        "tcp_enabled": tcp_enabled.lower() == "true",
        "tcp_port": tcp_port, "tcp_interval": tcp_interval,
        "http_enabled": http_enabled.lower() == "true",
        "http_url": http_url, "http_interval": http_interval,
        "ssh_enabled": ssh_enabled.lower() == "true",
        "ssh_port": ssh_port, "ssh_interval": ssh_interval,
        "wmi_enabled": wmi_enabled.lower() == "true",
        "wmi_username": wmi_username, "wmi_password": wmi_password,
        "wmi_interval": wmi_interval,
        "netflow_enabled": netflow_enabled.lower() == "true",
        "sflow_enabled": sflow_enabled.lower() == "true",
        "syslog_enabled": syslog_enabled.lower() == "true",
        "syslog_port": syslog_port,
        "syslog_source_ip": syslog_source_ip,
        "is_active": is_active.lower() == "true",
    })
    if device["is_active"]:
        schedule_device(device)
    else:
        unschedule_device(device_id)
    _ids = [int(x) for x in snmp_template_ids.split(",") if x.strip()]
    crud.set_device_templates(device_id, _ids)
    return {"ok": True}


@router.delete("/api/devices/{device_id}")
def api_delete_device(device_id: int, request: Request):
    require_operator(request)
    if not crud.get_device(device_id):
        raise HTTPException(status_code=404)
    unschedule_device(device_id)
    crud.delete_device(device_id)
    return {"ok": True}


# ── API: Notes ────────────────────────────────────────────────

@router.get("/api/devices/{device_id}/notes")
def api_get_notes(device_id: int, request: Request):
    _check(request)
    user = _get_session_user(request)
    is_operator_or_above = _ROLE_RANK.get(user.get("role", "user"), 0) >= _ROLE_RANK["operator"]
    return crud.get_notes(device_id, include_operator=is_operator_or_above)


@router.post("/api/devices/{device_id}/notes")
def api_create_note(
    device_id: int, request: Request,
    title: str = Form(...), content: str = Form(""),
    is_operator_note: int = Form(0),
):
    _check(request)
    user = _get_session_user(request)
    is_op = _ROLE_RANK.get(user.get("role", "user"), 0) >= _ROLE_RANK["operator"]
    # Operator-Notizen dürfen nur von Operator/Admin erstellt werden
    if is_operator_note and not is_op:
        raise HTTPException(status_code=403, detail="Unzureichende Berechtigung für Operator-Notiz")
    note = crud.create_note(device_id, title, content, is_operator_note=bool(is_operator_note))
    return {"id": note["id"], "title": note["title"]}


@router.delete("/api/notes/{note_id}")
def api_delete_note(note_id: int, request: Request):
    require_operator(request)
    crud.delete_note(note_id)
    return {"ok": True}


# ── API: Icon Upload ──────────────────────────────────────────

@router.post("/api/devices/{device_id}/icon")
async def api_upload_icon(device_id: int, request: Request, file: UploadFile = File(...)):
    require_operator(request)
    if not crud.get_device(device_id):
        raise HTTPException(status_code=404)
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="Ungültiges Dateiformat")
    icon_name = f"custom_{device_id}{ext}"
    dest = Path(UPLOAD_DIR) / icon_name
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    crud.update_device_icon(device_id, icon_name)
    return {"icon_name": icon_name}


# ── API: Icon Reset ───────────────────────────────────────────

@router.delete("/api/devices/{device_id}/icon")
def api_reset_icon(device_id: int, request: Request):
    require_operator(request)
    device = crud.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404)
    if device["icon_name"] and device["icon_name"].startswith("custom_"):
        icon_path = Path(UPLOAD_DIR) / device["icon_name"]
        if icon_path.exists():
            icon_path.unlink()
    crud.update_device_icon(device_id, None)
    return {"ok": True}


# ── API: SNMP Metric Config ────────────────────────────────────

@router.get("/api/devices/{device_id}/snmp-config")
def api_get_snmp_config(device_id: int, request: Request):
    _check(request)
    if not crud.get_device(device_id):
        raise HTTPException(status_code=404)
    return {"disabled": crud.get_snmp_disabled(device_id)}


@router.post("/api/devices/{device_id}/snmp-config")
async def api_set_snmp_config(device_id: int, request: Request):
    require_operator(request)
    if not crud.get_device(device_id):
        raise HTTPException(status_code=404)
    body = await request.json()
    crud.set_snmp_disabled(device_id, body.get("disabled", []))
    return {"ok": True}


# ── API: Manual Method Check ──────────────────────────────────

@router.post("/api/check/device/{device_id}/{method}")
def api_check_method(device_id: int, method: str, request: Request):
    _check(request)
    if not crud.get_device(device_id):
        raise HTTPException(status_code=404)
    ok = run_device_check(device_id, method)
    if not ok:
        raise HTTPException(status_code=400, detail="Unknown method")
    return {"ok": True, "method": method}


# ── API: Manual Ping ──────────────────────────────────────────

@router.get("/api/devices/{device_id}/ping")
def api_ping(device_id: int, request: Request):
    _check(request)
    device = crud.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404)
    from app.monitoring.icmp_check import ping
    return ping(device["ip_address"])


# ── API: Check Now (returns result immediately) ───────────────

@router.get("/api/devices/{device_id}/check_now/{method}")
def api_check_now(device_id: int, method: str, request: Request):
    """Run a single check and return the result immediately (no DB write)."""
    _check(request)
    device = crud.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404)
    if method == "tcp":
        result = tcp_check(device["ip_address"], device.get("tcp_port", 80))
        return {"reachable": result["reachable"], "connect_ms": result.get("connect_ms"),
                "port": device.get("tcp_port")}
    elif method == "http":
        url = device.get("http_url", "")
        if not url:
            raise HTTPException(status_code=400, detail="Keine HTTP-URL konfiguriert")
        result = http_check(url)
        return {"reachable": result["reachable"], "status_code": result.get("status_code"),
                "response_ms": result.get("response_ms"), "error": result.get("error")}
    elif method == "ssh":
        result = ssh_check(device["ip_address"], device.get("ssh_port", 22))
        return {"reachable": result["reachable"], "connect_ms": result.get("connect_ms"),
                "banner": result.get("banner"), "port": device.get("ssh_port", 22)}
    else:
        raise HTTPException(status_code=400, detail="Methode nicht unterstützt")


# ── API: Syslog ───────────────────────────────────────────────

@router.get("/api/devices/{device_id}/syslog")
def api_get_syslog(device_id: int, request: Request,
                   hours: int = 24, limit: int = 200, min_severity: int = None):
    _check(request)
    if not crud.get_device(device_id):
        raise HTTPException(status_code=404)
    return crud.get_syslog_messages(device_id, hours=hours, limit=limit,
                                    min_severity=min_severity)


@router.get("/api/devices/{device_id}/syslog/stats")
def api_syslog_stats(device_id: int, request: Request, hours: int = 24):
    _check(request)
    if not crud.get_device(device_id):
        raise HTTPException(status_code=404)
    return crud.get_syslog_stats(device_id, hours=hours)


# ── API: Template Entries for device ─────────────────────────

@router.get("/api/devices/{device_id}/template-entries")
def api_get_device_template_entries(device_id: int, request: Request):
    _check(request)
    if not crud.get_device(device_id):
        raise HTTPException(status_code=404)
    return crud.get_all_template_entries_for_device(device_id)


# ── SNMP Hidden metrics (per user) ───────────────────────────

@router.get("/api/devices/{device_id}/snmp-hidden")
def api_get_snmp_hidden(device_id: int, request: Request):
    _check(request)
    uid = request.session.get("user_id")
    return {"hidden": crud.get_snmp_hidden(uid, device_id)}


@router.post("/api/devices/{device_id}/snmp-hidden")
async def api_set_snmp_hidden(device_id: int, request: Request):
    _check(request)
    uid = request.session.get("user_id")
    body = await request.json()
    crud.set_snmp_hidden(uid, device_id, [int(x) for x in body.get("hidden", [])])
    return {"ok": True}


# ── Syslog Resolve ─────────────────────────────────────────────

@router.delete("/api/syslog/messages/{msg_id}")
def api_resolve_syslog(msg_id: int, request: Request):
    _check(request)
    crud.delete_syslog_message(msg_id)
    return {"ok": True}


# ── SNMP Alert endpoints ───────────────────────────────────────

@router.get("/api/devices/{device_id}/snmp-alerts")
def api_get_snmp_alerts(device_id: int, request: Request):
    _check(request)
    return crud.get_snmp_alerts_grouped(device_id)


@router.post("/api/devices/{device_id}/snmp-alerts/entry/{entry_id}/rules")
async def api_add_alert_rule(device_id: int, entry_id: int, request: Request):
    _check(request)
    body = await request.json()
    op   = body.get("operator", ">")
    thr  = body.get("threshold", "")
    sev  = body.get("severity", "warning")
    if op not in (">", "<", "=", "!="):
        raise HTTPException(status_code=400, detail="operator must be >, <, = or !=")
    if sev not in ("critical", "warning", "info"):
        raise HTTPException(status_code=400, detail="invalid severity")
    rule = crud.add_snmp_alert_rule(device_id, entry_id, op, thr, sev)
    return rule


@router.put("/api/devices/{device_id}/snmp-alerts/rule/{rule_id}")
async def api_update_alert_rule(device_id: int, rule_id: int, request: Request):
    _check(request)
    body = await request.json()
    op   = body.get("operator", ">")
    thr  = body.get("threshold", "")
    sev  = body.get("severity", "warning")
    if op not in (">", "<", "=", "!="):
        raise HTTPException(status_code=400, detail="operator must be >, <, = or !=")
    if sev not in ("critical", "warning", "info"):
        raise HTTPException(status_code=400, detail="invalid severity")
    crud.update_snmp_alert_rule(rule_id, op, thr, sev)
    return {"ok": True}


@router.delete("/api/devices/{device_id}/snmp-alerts/rule/{rule_id}")
def api_delete_alert_rule(device_id: int, rule_id: int, request: Request):
    _check(request)
    crud.delete_snmp_alert_rule(rule_id)
    return {"ok": True}


@router.delete("/api/devices/{device_id}/snmp-alerts/entry/{entry_id}")
def api_delete_entry_alerts(device_id: int, entry_id: int, request: Request):
    _check(request)
    crud.delete_entry_alerts(device_id, entry_id)
    return {"ok": True}


@router.put("/api/devices/{device_id}/snmp-alerts/entry/{entry_id}/enabled")
async def api_set_entry_alert_enabled(device_id: int, entry_id: int, request: Request):
    _check(request)
    body = await request.json()
    crud.set_entry_alert_enabled(device_id, entry_id, 1 if body.get("enabled") else 0)
    return {"ok": True}


@router.get("/api/snmp-alerts/triggered")
def api_get_triggered_alerts(request: Request):
    _check(request)
    return crud.get_all_triggered_alerts()


# ── User Dashboard Prefs ───────────────────────────────────────

@router.get("/api/user/dashboard-prefs")
def api_get_dashboard_prefs(request: Request):
    _check(request)
    uid = request.session.get("user_id")
    return {"prefs": crud.get_user_dashboard_prefs(uid)}


@router.put("/api/user/dashboard-prefs")
async def api_set_dashboard_prefs(request: Request):
    _check(request)
    import json as _json
    uid  = request.session.get("user_id")
    body = await request.json()
    crud.set_user_dashboard_prefs(uid, _json.dumps(body.get("prefs", {})))
    return {"ok": True}


# ── ICMP Alert endpoints ───────────────────────────────────────

@router.get("/api/devices/{device_id}/icmp-alerts")
def api_get_icmp_alerts(device_id: int, request: Request):
    _check(request)
    rules = crud.get_icmp_alert_rules(device_id)
    state = crud.get_icmp_alert_state(device_id)
    return {"rules": rules, "state": state}


@router.post("/api/devices/{device_id}/icmp-alerts")
async def api_add_icmp_alert_rule(device_id: int, request: Request):
    _check(request)
    body = await request.json()
    op  = body.get("operator", ">")
    thr = body.get("threshold", "")
    sev = body.get("severity", "warning")
    if op not in (">", "<", "=", "!="):
        raise HTTPException(status_code=400, detail="operator must be >, <, = or !=")
    if sev not in ("critical", "warning", "info"):
        raise HTTPException(status_code=400, detail="invalid severity")
    rule = crud.add_icmp_alert_rule(device_id, op, thr, sev)
    return rule


@router.put("/api/devices/{device_id}/icmp-alerts/{rule_id}")
async def api_update_icmp_alert_rule(device_id: int, rule_id: int, request: Request):
    _check(request)
    body = await request.json()
    op  = body.get("operator", ">")
    thr = body.get("threshold", "")
    sev = body.get("severity", "warning")
    if op not in (">", "<", "=", "!="):
        raise HTTPException(status_code=400, detail="operator must be >, <, = or !=")
    if sev not in ("critical", "warning", "info"):
        raise HTTPException(status_code=400, detail="invalid severity")
    crud.update_icmp_alert_rule(rule_id, op, thr, sev)
    return {"ok": True}


@router.delete("/api/devices/{device_id}/icmp-alerts/{rule_id}")
def api_delete_icmp_alert_rule(device_id: int, rule_id: int, request: Request):
    _check(request)
    crud.delete_icmp_alert_rule(rule_id)
    return {"ok": True}
