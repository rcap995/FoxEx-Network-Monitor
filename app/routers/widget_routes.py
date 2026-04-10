"""Dashboard widget API routes for TCP, HTTP, SSH, and NetFlow widgets."""
from fastapi import APIRouter, Request
from app import crud

router = APIRouter(tags=["widgets"])


def _require_login(request: Request) -> dict:
    from fastapi import HTTPException
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401)
    user = crud.get_user(uid)
    if not user:
        raise HTTPException(status_code=401)
    return user


@router.get("/api/dashboard/tcp-check")
def api_tcp_check(request: Request):
    _require_login(request)
    return crud.get_tcp_check_status()


@router.get("/api/dashboard/http-check")
def api_http_check(request: Request):
    _require_login(request)
    return crud.get_http_check_status()


@router.get("/api/dashboard/ssh-check")
def api_ssh_check(request: Request):
    _require_login(request)
    return crud.get_ssh_check_status()


@router.get("/api/dashboard/netflow-top-talkers")
def api_netflow_top_talkers(request: Request, hours: int = 24, limit: int = 10):
    _require_login(request)
    return crud.get_netflow_top_talkers(hours, limit)
