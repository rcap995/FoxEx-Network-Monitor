"""Shared Jinja2Templates instance with custom filters — import from here."""
from datetime import datetime
from fastapi.templating import Jinja2Templates
from app.config import APP_VERSION

templates = Jinja2Templates(directory="templates")
templates.env.globals["APP_VERSION"] = APP_VERSION


def _fmt_dt(value, fmt="%d.%m.%Y %H:%M"):
    if not value:
        return "–"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime(fmt)


templates.env.filters["dt"]   = _fmt_dt
templates.env.filters["date"] = lambda v: _fmt_dt(v, "%d.%m.%Y")
