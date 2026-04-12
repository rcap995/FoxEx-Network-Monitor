from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import SECRET_KEY, APP_TITLE, APP_VERSION
from app.database import init_db
from app import crud
from app.auth import get_password_hash
from app.monitoring.scheduler import start_scheduler
from app.monitoring.netflow_collector import start_netflow_collector
from app.monitoring.sflow_collector import start_sflow_collector
from app.monitoring.syslog_collector import start_syslog_collector
from app.monitoring.trap_collector import start_trap_collector
from app.routers import auth_routes, device_routes, topology_routes, metric_routes
from app.routers import user_routes, settings_routes, url_monitor_routes, maintenance_routes, report_routes, widget_routes
from app.routers import ssh_service_routes
from app.templates_config import templates  # noqa: F401 – registers filters

# Ensure required directories exist
for d in ["data", "uploads/icons", "static/icons"]:
    Path(d).mkdir(parents=True, exist_ok=True)

# Initialise database tables
init_db()

app = FastAPI(title=APP_TITLE, version=APP_VERSION)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=86400)

app.mount("/static",  StaticFiles(directory="static"),  name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.include_router(auth_routes.router)
app.include_router(device_routes.router)
app.include_router(topology_routes.router)
app.include_router(metric_routes.router)
app.include_router(user_routes.router)
app.include_router(settings_routes.router)
app.include_router(url_monitor_routes.router)
app.include_router(maintenance_routes.router)
app.include_router(report_routes.router)
app.include_router(widget_routes.router)
app.include_router(ssh_service_routes.router)


@app.on_event("startup")
async def startup_event():
    # Create default admin user
    if not crud.get_user_by_username("admin"):
        crud.create_user("admin", get_password_hash("admin"))
    # Ensure topology record exists
    crud.ensure_topology_exists()
    # Start background monitoring
    start_scheduler()
    # Start flow collectors (bind errors are logged but don't crash the app)
    start_netflow_collector(port=2055)
    start_sflow_collector(port=6343)
    start_syslog_collector(port=514)
    trap_port = int(crud.get_setting("snmp.trap.port", "162"))
    start_trap_collector(port=trap_port)


@app.get("/")
def root(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url="/login", status_code=302)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
