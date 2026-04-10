"""Routes for maintenance windows and alert acknowledgment."""
from fastapi import APIRouter, Request, HTTPException
from app import crud
from app.auth import require_operator

router = APIRouter(tags=["maintenance"])


def _require_login(request: Request) -> dict:
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401)
    user = crud.get_user(uid)
    if not user:
        raise HTTPException(status_code=401)
    return user


# ── Maintenance Windows ────────────────────────────────────────

@router.get("/api/maintenance/")
async def list_maintenance_windows(req: Request):
    _require_login(req)
    return crud.get_maintenance_windows()


@router.post("/api/maintenance/")
async def create_maintenance_window(req: Request):
    require_operator(req)
    body = await req.json()
    if not body.get("start_dt") or not body.get("end_dt"):
        raise HTTPException(400, "start_dt and end_dt are required")
    mw = crud.create_maintenance_window(
        name=body.get("name", "Wartungsfenster").strip() or "Wartungsfenster",
        device_id=body.get("device_id") or None,
        start_dt=body["start_dt"],
        end_dt=body["end_dt"],
        repeat_weekly=1 if body.get("repeat_weekly") else 0,
        enabled=1 if body.get("enabled", True) else 0,
    )
    return mw


@router.put("/api/maintenance/{mw_id}")
async def update_maintenance_window(req: Request, mw_id: int):
    require_operator(req)
    body = await req.json()
    if not body.get("start_dt") or not body.get("end_dt"):
        raise HTTPException(400, "start_dt and end_dt are required")
    mw = crud.update_maintenance_window(
        mw_id,
        name=body.get("name", "Wartungsfenster").strip() or "Wartungsfenster",
        device_id=body.get("device_id") or None,
        start_dt=body["start_dt"],
        end_dt=body["end_dt"],
        repeat_weekly=1 if body.get("repeat_weekly") else 0,
        enabled=1 if body.get("enabled", True) else 0,
    )
    if not mw:
        raise HTTPException(404, "Maintenance window not found")
    return mw


@router.delete("/api/maintenance/{mw_id}")
async def delete_maintenance_window(req: Request, mw_id: int):
    require_operator(req)
    crud.delete_maintenance_window(mw_id)
    return {"ok": True}


# ── Active Alerts ──────────────────────────────────────────────

@router.get("/api/alerts/active")
async def get_active_alerts(req: Request):
    _require_login(req)
    return crud.get_active_alerts()


@router.get("/api/alerts/active/{widget_type}")
async def get_active_alerts_by_widget(req: Request, widget_type: str):
    _require_login(req)
    return crud.get_active_alerts_by_widget(widget_type)


@router.get("/api/alerts/unacked-counts")
async def get_unacked_counts(req: Request):
    _require_login(req)
    return crud.get_unacked_alert_counts()


@router.post("/api/alerts/ack/{widget_type}/{entity_id:path}")
async def ack_alert(req: Request, widget_type: str, entity_id: str):
    require_operator(req)
    body = {}
    try:
        body = await req.json()
    except Exception:
        pass
    acked_by = req.session.get("username", "admin")
    comment  = str(body.get("comment", "")).strip()
    ok = crud.ack_active_alert(widget_type, entity_id, acked_by, comment)
    if not ok:
        raise HTTPException(404, "Alert not found")
    return {"ok": True}


@router.delete("/api/alerts/ack/{widget_type}/{entity_id:path}")
async def remove_ack(req: Request, widget_type: str, entity_id: str):
    require_operator(req)
    crud.remove_alert_ack(widget_type, entity_id)
    return {"ok": True}
