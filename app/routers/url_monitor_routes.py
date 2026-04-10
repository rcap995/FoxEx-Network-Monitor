"""URL Monitor (DNS check) routes and widget notification rule routes."""
from fastapi import APIRouter, Request, HTTPException
from app import crud
from app.monitoring import scheduler

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


# ── URL Monitors ────────────────────────────────────────────────

@router.get("/api/url-monitors")
def api_list_url_monitors(request: Request):
    _require_login(request)
    return crud.get_url_monitors()


@router.post("/api/url-monitors")
async def api_create_url_monitor(request: Request):
    _require_admin(request)
    body = await request.json()
    name = body.get("name", "").strip()
    url  = body.get("url", "").strip()
    if not name or not url:
        raise HTTPException(status_code=400, detail="Name und URL erforderlich")
    from app.config import DEFAULT_DNS_INTERVAL
    interval_s = int(body.get("interval_s", DEFAULT_DNS_INTERVAL))
    monitor = crud.create_url_monitor(name, url, interval_s)
    scheduler.schedule_dns_monitor(monitor)
    return monitor


@router.put("/api/url-monitors/{monitor_id}")
async def api_update_url_monitor(monitor_id: int, request: Request):
    _require_admin(request)
    if not crud.get_url_monitor(monitor_id):
        raise HTTPException(status_code=404)
    body = await request.json()
    name      = body.get("name", "").strip()
    url       = body.get("url", "").strip()
    from app.config import DEFAULT_DNS_INTERVAL
    interval_s = int(body.get("interval_s", DEFAULT_DNS_INTERVAL))
    enabled    = 1 if body.get("enabled", True) else 0
    if not name or not url:
        raise HTTPException(status_code=400, detail="Name und URL erforderlich")
    crud.update_url_monitor(monitor_id, name, url, interval_s, enabled)
    monitor = crud.get_url_monitor(monitor_id)
    if enabled:
        scheduler.schedule_dns_monitor(monitor)
    else:
        scheduler.unschedule_dns_monitor(monitor_id)
    return {"ok": True}


@router.delete("/api/url-monitors/{monitor_id}")
def api_delete_url_monitor(monitor_id: int, request: Request):
    _require_admin(request)
    if not crud.get_url_monitor(monitor_id):
        raise HTTPException(status_code=404)
    scheduler.unschedule_dns_monitor(monitor_id)
    crud.delete_url_monitor(monitor_id)
    return {"ok": True}


@router.get("/api/url-monitors/{monitor_id}/results")
def api_url_monitor_results(monitor_id: int, request: Request):
    _require_login(request)
    return crud.get_url_monitor_results(monitor_id, limit=100)


# ── Widget Notification Rules ───────────────────────────────────

VALID_WIDGET_TYPES = {
    "status", "icmp_avg", "device_latency",
    "packet_loss", "syslog", "snmp", "dns",
}


@router.get("/api/notifications/rules/{widget_type}")
def api_get_notif_rule(widget_type: str, request: Request):
    _require_login(request)
    if widget_type not in VALID_WIDGET_TYPES:
        raise HTTPException(status_code=400, detail="Unbekannter Widget-Typ")
    rule = crud.get_widget_notification_rule(widget_type)
    if not rule:
        rule = {"widget_type": widget_type, "enabled": 0, "threshold": "",
                "severity_filter": "", "min_duration_minutes": 0, "id": None}
    exceptions = crud.get_widget_notification_exceptions(rule.get("id") or 0)
    rule["exceptions"] = exceptions
    return rule


@router.post("/api/notifications/rules/{widget_type}")
async def api_save_notif_rule(widget_type: str, request: Request):
    _require_admin(request)
    if widget_type not in VALID_WIDGET_TYPES:
        raise HTTPException(status_code=400, detail="Unbekannter Widget-Typ")
    body = await request.json()
    enabled              = 1 if body.get("enabled") else 0
    threshold            = str(body.get("threshold", "")).strip()
    severity_filter      = str(body.get("severity_filter", "")).strip()
    min_duration_minutes = int(body.get("min_duration_minutes", 0))
    message              = str(body.get("message", "")).strip()
    crud.upsert_widget_notification_rule(
        widget_type, enabled, threshold, severity_filter, min_duration_minutes, message
    )
    return {"ok": True}


@router.post("/api/notifications/rules/{widget_type}/exceptions")
async def api_add_notif_exception(widget_type: str, request: Request):
    _require_admin(request)
    if widget_type not in VALID_WIDGET_TYPES:
        raise HTTPException(status_code=400, detail="Unbekannter Widget-Typ")
    rule = crud.get_widget_notification_rule(widget_type)
    if not rule:
        # Auto-create disabled rule so we can attach exceptions
        crud.upsert_widget_notification_rule(widget_type, 0, "", "", 0)
        rule = crud.get_widget_notification_rule(widget_type)
    body  = await request.json()
    value = str(body.get("value", "")).strip()
    if not value:
        raise HTTPException(status_code=400, detail="Wert erforderlich")
    return crud.add_widget_notification_exception(rule["id"], value)


@router.delete("/api/notifications/exceptions/{exc_id}")
def api_delete_notif_exception(exc_id: int, request: Request):
    _require_admin(request)
    crud.delete_widget_notification_exception(exc_id)
    return {"ok": True}
