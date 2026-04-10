from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from app.templates_config import templates
from app.auth import authenticate_user, get_password_hash, require_login
from app import crud

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user = authenticate_user(username, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Ungültige Anmeldedaten"},
            status_code=401,
        )
    request.session["user_id"]        = user["id"]
    request.session["username"]       = user["username"]
    request.session["role"]           = user.get("role", "user")
    request.session["full_name"]      = user.get("full_name", "")
    request.session["force_pw_change"] = bool(user.get("force_pw_change", 0))
    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@router.post("/api/auth/change-password")
async def api_change_password(request: Request):
    """User changes their own password (also clears force_pw_change flag)."""
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401)
    body = await request.json()
    current  = (body.get("current_password") or "").strip()
    new_pw   = (body.get("new_password") or "").strip()
    if len(new_pw) < 6:
        raise HTTPException(status_code=400, detail="Passwort muss mindestens 6 Zeichen haben")
    user = crud.get_user(uid)
    if not user:
        raise HTTPException(status_code=401)
    from app.auth import verify_password
    if not verify_password(current, user["hashed_password"]):
        raise HTTPException(status_code=400, detail="Aktuelles Passwort ist falsch")
    crud.update_user_profile(uid, user.get("full_name", ""),
                             hashed_password=get_password_hash(new_pw))
    request.session["force_pw_change"] = False
    return {"ok": True}
