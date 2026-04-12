"""SSH service monitor routes."""
from fastapi import APIRouter, HTTPException, Request
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


# ── List ────────────────────────────────────────────────────────

@router.get("/api/ssh-services")
def api_list_ssh_services(request: Request):
    _require_login(request)
    return crud.get_ssh_service_monitors()


# ── Create ──────────────────────────────────────────────────────

@router.post("/api/ssh-services")
async def api_create_ssh_service(request: Request):
    _require_admin(request)
    body = await request.json()
    name         = body.get("name", "").strip()
    host         = body.get("host", "").strip()
    port         = int(body.get("port", 22))
    username     = body.get("username", "").strip()
    password     = body.get("password", "")
    service_name = body.get("service_name", "").strip()
    interval     = int(body.get("check_interval", 60))
    if not name or not host or not username or not service_name:
        raise HTTPException(status_code=400, detail="Name, Host, Benutzername und Dienst sind Pflichtfelder")
    monitor = crud.create_ssh_service_monitor(name, host, port, username, password, service_name, interval)
    scheduler.schedule_ssh_service_monitor(monitor)
    return monitor


# ── Update ──────────────────────────────────────────────────────

@router.put("/api/ssh-services/{monitor_id}")
async def api_update_ssh_service(monitor_id: int, request: Request):
    _require_admin(request)
    if not crud.get_ssh_service_monitor(monitor_id):
        raise HTTPException(status_code=404)
    body = await request.json()
    name         = body.get("name", "").strip()
    host         = body.get("host", "").strip()
    port         = int(body.get("port", 22))
    username     = body.get("username", "").strip()
    password     = body.get("password", "")
    service_name = body.get("service_name", "").strip()
    interval     = int(body.get("check_interval", 60))
    enabled      = 1 if body.get("enabled", True) else 0
    if not name or not host or not username or not service_name:
        raise HTTPException(status_code=400, detail="Name, Host, Benutzername und Dienst sind Pflichtfelder")
    crud.update_ssh_service_monitor(
        monitor_id, name, host, port, username, password, service_name, interval, enabled
    )
    monitor = crud.get_ssh_service_monitor(monitor_id)
    if enabled:
        scheduler.schedule_ssh_service_monitor(monitor)
    else:
        scheduler.unschedule_ssh_service_monitor(monitor_id)
    return {"ok": True}


# ── Delete ──────────────────────────────────────────────────────

@router.delete("/api/ssh-services/{monitor_id}")
def api_delete_ssh_service(monitor_id: int, request: Request):
    _require_admin(request)
    if not crud.get_ssh_service_monitor(monitor_id):
        raise HTTPException(status_code=404)
    scheduler.unschedule_ssh_service_monitor(monitor_id)
    crud.delete_ssh_service_monitor(monitor_id)
    return {"ok": True}


# ── History ─────────────────────────────────────────────────────

@router.get("/api/ssh-services/{monitor_id}/history")
def api_ssh_service_history(monitor_id: int, request: Request):
    _require_login(request)
    if not crud.get_ssh_service_monitor(monitor_id):
        raise HTTPException(status_code=404)
    return crud.get_ssh_service_history(monitor_id, limit=50)


# ── Manual check ────────────────────────────────────────────────

@router.post("/api/ssh-services/{monitor_id}/check")
def api_ssh_service_check_now(monitor_id: int, request: Request):
    _require_admin(request)
    monitor = crud.get_ssh_service_monitor(monitor_id)
    if not monitor:
        raise HTTPException(status_code=404)
    from app.monitoring.ssh_service_check import ssh_service_check
    result = ssh_service_check(
        monitor["host"], monitor["port"],
        monitor["username"], monitor["password"],
        monitor["service_name"],
    )
    crud.update_ssh_service_status(monitor_id, result["status"], result["output"], result["response_ms"])
    return result
