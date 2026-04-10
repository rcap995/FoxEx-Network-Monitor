from datetime import datetime, timedelta
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import HTMLResponse
from app.templates_config import templates
from app import crud
from app.database import get_db

router = APIRouter()


def _check(request: Request):
    if not request.session.get("user_id"):
        raise HTTPException(status_code=302, headers={"Location": "/login"})


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request):
    _check(request)
    from app import crud
    user = crud.get_user(request.session.get("user_id"))
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "username": request.session.get("username"),
        "user_role": user.get("role", "user") if user else "user",
        "user_full_name": user.get("full_name", "") if user else "",
    })


@router.get("/api/devices/{device_id}/metrics")
def api_device_metrics(
    device_id: int, request: Request,
    metric: str = Query(None),
    hours: int = Query(24),
    limit: int = Query(200),
):
    _check(request)
    if not crud.get_device(device_id):
        raise HTTPException(status_code=404)
    return crud.get_metrics(device_id, metric, hours, limit)


@router.get("/api/devices/{device_id}/metrics/latest")
def api_latest_metrics(device_id: int, request: Request):
    _check(request)
    if not crud.get_device(device_id):
        raise HTTPException(status_code=404)
    return crud.get_latest_metrics(device_id)


@router.get("/api/dashboard/summary")
def api_dashboard_summary(request: Request):
    _check(request)
    devices = crud.get_all_devices(active_only=True)
    total   = len(devices)
    online  = sum(1 for d in devices if d["status"] == "online")
    offline = sum(1 for d in devices if d["status"] == "offline")
    unknown = sum(1 for d in devices if d["status"] == "unknown")

    device_list = []
    for d in devices:
        latest = crud.get_latest_latency(d["id"])
        icmp_state = crud.get_icmp_alert_state(d["id"])
        icmp_sev = icmp_state["severity"] if icmp_state and icmp_state.get("triggered") else None
        device_list.append({
            "id": d["id"], "name": d["name"], "ip_address": d["ip_address"],
            "device_type": d["device_type"], "status": d["status"],
            "icon_name": d["icon_name"], "last_seen": d["last_seen"],
            "latency_ms": latest["value_float"] if latest else None,
            "icmp_alert_severity": icmp_sev,
        })

    return {"total": total, "online": online, "offline": offline,
            "unknown": unknown, "devices": device_list}


@router.get("/api/dashboard/latency-trend")
def api_latency_trend(request: Request, hours: int = Query(24)):
    """Average ICMP latency per hour across all devices."""
    _check(request)
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as db:
        rows = db.execute("""
            SELECT strftime('%Y-%m-%dT%H:00:00', timestamp) AS bucket,
                   ROUND(AVG(value_float), 2)               AS avg_ms,
                   COUNT(*)                                  AS samples
            FROM metric_history
            WHERE metric_name = 'icmp_latency'
              AND value_float IS NOT NULL
              AND timestamp  >= ?
            GROUP BY bucket
            ORDER BY bucket ASC
        """, (since,)).fetchall()
    return [{"time": r["bucket"], "avg_ms": r["avg_ms"], "samples": r["samples"]} for r in rows]


@router.get("/api/dashboard/packet-loss-trend")
def api_packet_loss_trend(request: Request, hours: int = Query(24)):
    """Average packet loss per hour."""
    _check(request)
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as db:
        rows = db.execute("""
            SELECT strftime('%Y-%m-%dT%H:00:00', timestamp) AS bucket,
                   ROUND(AVG(value_float), 2)               AS avg_loss
            FROM metric_history
            WHERE metric_name = 'icmp_packet_loss'
              AND value_float IS NOT NULL
              AND timestamp  >= ?
            GROUP BY bucket
            ORDER BY bucket ASC
        """, (since,)).fetchall()
    return [{"time": r["bucket"], "avg_loss": r["avg_loss"]} for r in rows]


@router.get("/api/dashboard/recent-events")
def api_recent_events(request: Request, limit: int = Query(20)):
    """Latest status changes (online/offline transitions)."""
    _check(request)
    with get_db() as db:
        rows = db.execute("""
            SELECT d.name, d.ip_address, d.status, d.last_seen,
                   mh.value_str AS latency, mh.timestamp
            FROM devices d
            LEFT JOIN metric_history mh ON mh.device_id = d.id
              AND mh.metric_name = 'icmp_latency'
              AND mh.id = (
                  SELECT id FROM metric_history
                  WHERE device_id = d.id AND metric_name = 'icmp_latency'
                  ORDER BY timestamp DESC LIMIT 1
              )
            WHERE d.is_active = 1
            ORDER BY COALESCE(mh.timestamp, d.created_at) DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


# ── Check-All / Check-Device ──────────────────────────────────

@router.post("/api/check/all")
def api_check_all(request: Request):
    """Trigger all monitoring jobs immediately."""
    _check(request)
    from app.monitoring.scheduler import trigger_all_now
    count = trigger_all_now()
    return {"triggered": count, "message": f"{count} Jobs ausgelöst"}


@router.post("/api/check/device/{device_id}")
def api_check_device(device_id: int, request: Request):
    """Trigger all monitoring jobs for one device immediately."""
    _check(request)
    from app.monitoring.scheduler import trigger_device_now
    count = trigger_device_now(device_id)
    return {"triggered": count, "message": f"{count} Jobs für Gerät {device_id} ausgelöst"}
