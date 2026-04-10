"""Routes for SLA / availability reports."""
import csv
import io
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from app import crud
from app.templates_config import templates

router = APIRouter(tags=["reports"])


def _require_login(request: Request) -> dict:
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401)
    user = crud.get_user(uid)
    if not user:
        raise HTTPException(status_code=401)
    return user


# ── HTML page ──────────────────────────────────────────────────

@router.get("/reports/sla")
def report_sla_page(request: Request):
    _require_login(request)
    return templates.TemplateResponse("report_sla.html", {"request": request})


# ── JSON API ───────────────────────────────────────────────────

@router.get("/api/reports/sla")
def api_sla_report(request: Request, days: int = 30):
    _require_login(request)
    if days not in (1, 7, 14, 30, 60, 90):
        days = 30
    return {
        "days":     days,
        "devices":  crud.get_all_devices_sla(days),
        "monitors": crud.get_all_url_monitors_sla(days),
    }


# ── CSV exports ────────────────────────────────────────────────

@router.get("/api/reports/sla/export/devices.csv")
def export_devices_csv(request: Request, days: int = 30):
    _require_login(request)
    if days not in (1, 7, 14, 30, 60, 90):
        days = 30
    data = crud.get_all_devices_sla(days)

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Gerät", "IP-Adresse", "Verfügbarkeit %", "Ausfallzeit (min)",
                "Ø Latenz (ms)", "Ø Paketverlust %", "Prüfungen gesamt",
                "Online", "Offline", "Erster Check", "Letzter Check"])
    for d in data:
        w.writerow([
            d.get("name", ""),
            d.get("ip_address", ""),
            d.get("uptime_pct", ""),
            d.get("downtime_min", ""),
            d.get("avg_latency_ms", ""),
            d.get("avg_packet_loss_pct", ""),
            d.get("total_checks", 0),
            d.get("online_checks", 0),
            d.get("offline_checks", 0),
            d.get("first_check", ""),
            d.get("last_check", ""),
        ])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=sla_geraete_{days}d.csv"},
    )


@router.get("/api/reports/sla/export/monitors.csv")
def export_monitors_csv(request: Request, days: int = 30):
    _require_login(request)
    if days not in (1, 7, 14, 30, 60, 90):
        days = 30
    data = crud.get_all_url_monitors_sla(days)

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Name", "URL", "Verfügbarkeit %", "Ausfallzeit (min)",
                "Ø Antwortzeit (ms)", "Prüfungen gesamt",
                "Online", "Offline", "Erster Check", "Letzter Check"])
    for m in data:
        w.writerow([
            m.get("name", ""),
            m.get("url", ""),
            m.get("uptime_pct", ""),
            m.get("downtime_min", ""),
            m.get("avg_response_ms", ""),
            m.get("total_checks", 0),
            m.get("online_checks", 0),
            m.get("offline_checks", 0),
            m.get("first_check", ""),
            m.get("last_check", ""),
        ])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=sla_urlmonitore_{days}d.csv"},
    )
