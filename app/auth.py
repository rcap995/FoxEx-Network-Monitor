import bcrypt
from fastapi import Request, HTTPException
from app import crud

# Role hierarchy: higher index = more permissions
_ROLE_RANK = {"user": 0, "operator": 1, "admin": 2}

ROLE_LABELS = {
    "admin":    "Admin",
    "operator": "Operator",
    "user":     "Benutzer",
}


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def authenticate_user(username: str, password: str) -> dict | None:
    user = crud.get_user_by_username(username)
    if not user or not verify_password(password, user["hashed_password"]):
        return None
    return user


def require_login(request: Request) -> int:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return user_id


def _get_session_user(request: Request) -> dict:
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401)
    user = crud.get_user(uid)
    if not user:
        raise HTTPException(status_code=401)
    return user


def require_role(request: Request, min_role: str) -> dict:
    """Raise 401/403 unless the session user has at least min_role."""
    user = _get_session_user(request)
    user_rank = _ROLE_RANK.get(user.get("role", "user"), 0)
    min_rank  = _ROLE_RANK.get(min_role, 0)
    if user_rank < min_rank:
        raise HTTPException(status_code=403, detail="Unzureichende Berechtigung")
    return user


def require_operator(request: Request) -> dict:
    """Admin or Operator access required."""
    return require_role(request, "operator")


def require_admin(request: Request) -> dict:
    """Admin-only access."""
    return require_role(request, "admin")
