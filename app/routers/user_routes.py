"""User profile, admin user management, and app info routes."""
import httpx
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse

from app import crud
from app.auth import get_password_hash, verify_password
from app.config import APP_VERSION
from app.templates_config import templates

router = APIRouter()


def _require_login(request: Request) -> dict:
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    user = crud.get_user(uid)
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return user


def _require_admin(request: Request) -> dict:
    user = _require_login(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Kein Zugriff – Administrator erforderlich")
    return user


# ── Profile ───────────────────────────────────────────────────

@router.post("/api/profile")
async def api_update_profile(request: Request):
    user = _require_login(request)
    body = await request.json()
    full_name = body.get("full_name", "").strip()
    new_pw    = body.get("new_password", "").strip()
    cur_pw    = body.get("current_password", "").strip()

    hashed = None
    if new_pw:
        if not cur_pw:
            raise HTTPException(status_code=400, detail="Aktuelles Passwort erforderlich")
        full_user = crud.get_user_by_username(user["username"])
        if not verify_password(cur_pw, full_user["hashed_password"]):
            raise HTTPException(status_code=400, detail="Aktuelles Passwort falsch")
        if len(new_pw) < 6:
            raise HTTPException(status_code=400, detail="Passwort muss mindestens 6 Zeichen haben")
        hashed = get_password_hash(new_pw)

    crud.update_user_profile(user["id"], full_name, hashed)
    request.session["full_name"] = full_name
    return {"ok": True}


# ── User Management (admin only) ──────────────────────────────

@router.get("/api/admin/users")
def api_list_users(request: Request):
    _require_admin(request)
    return crud.get_all_users()


@router.post("/api/admin/users")
async def api_create_user(request: Request):
    _require_admin(request)
    body = await request.json()
    username  = body.get("username", "").strip()
    password  = body.get("password", "").strip()
    full_name = body.get("full_name", "").strip()
    role      = body.get("role", "user")

    force_pw = 1 if body.get("force_pw_change") else 0
    if not username or not password:
        raise HTTPException(status_code=400, detail="Benutzername und Passwort erforderlich")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Passwort muss mindestens 6 Zeichen haben")
    if role not in ("admin", "operator", "user"):
        raise HTTPException(status_code=400, detail="Ungültige Rolle")
    if crud.get_user_by_username(username):
        raise HTTPException(status_code=409, detail="Benutzername bereits vergeben")

    user = crud.create_user_full(username, get_password_hash(password),
                                 full_name, role, force_pw_change=force_pw)
    return {"id": user["id"], "username": user["username"]}


@router.put("/api/admin/users/{user_id}/role")
async def api_set_role(user_id: int, request: Request):
    admin = _require_admin(request)
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Eigene Rolle kann nicht geändert werden")
    body = await request.json()
    role = body.get("role", "user")
    if role not in ("admin", "operator", "user"):
        raise HTTPException(status_code=400, detail="Ungültige Rolle")
    crud.update_user_role(user_id, role)
    return {"ok": True}


@router.put("/api/admin/users/{user_id}/password")
async def api_reset_password(user_id: int, request: Request):
    """Admin resets another user's password."""
    admin = _require_admin(request)
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Eigenes Passwort bitte über Profileinstellungen ändern")
    body = await request.json()
    new_pw = (body.get("password") or "").strip()
    if len(new_pw) < 6:
        raise HTTPException(status_code=400, detail="Passwort muss mindestens 6 Zeichen haben")
    force_pw = 1 if body.get("force_pw_change") else 0
    crud.admin_set_user_password(user_id, get_password_hash(new_pw), force_pw)
    return {"ok": True}


@router.delete("/api/admin/users/{user_id}")
def api_delete_user(user_id: int, request: Request):
    admin = _require_admin(request)
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Eigener Account kann nicht gelöscht werden")
    crud.delete_user(user_id)
    return {"ok": True}


# ── Info / Version ─────────────────────────────────────────────

@router.get("/api/info")
async def api_info(request: Request):
    _require_login(request)
    latest = None
    update_available = False
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(
                "https://api.github.com/repos/foxex-dev/foxex-network-monitor/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
            )
            if r.status_code == 200:
                data = r.json()
                latest = data.get("tag_name", "").lstrip("v")
                update_available = latest != APP_VERSION
    except Exception:
        pass
    return {
        "version": APP_VERSION,
        "latest": latest,
        "update_available": update_available,
    }


# ── Syslog Dashboard ──────────────────────────────────────────

@router.get("/api/dashboard/syslog-summary")
def api_syslog_summary(request: Request, hours: int = 24):
    _require_login(request)
    return crud.get_syslog_dashboard_summary(hours)


@router.get("/api/syslog/all")
def api_syslog_all(request: Request, hours: int = 24,
                   severity: str = None, limit: int = 300):
    _require_login(request)
    return crud.get_syslog_all_devices(hours, severity, limit)


# ── SNMP Traps ─────────────────────────────────────────────────

@router.get("/api/snmp-traps/summary")
def api_trap_summary(request: Request, hours: int = 24):
    _require_login(request)
    return crud.get_snmp_trap_summary(hours)


@router.get("/api/snmp-traps/all")
def api_traps_all(request: Request, hours: int = 24,
                  device_id: int = None, limit: int = 300):
    _require_login(request)
    return crud.get_snmp_traps(hours, device_id, limit)
