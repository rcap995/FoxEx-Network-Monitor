import json
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from app.templates_config import templates
from app import crud
from app.config import DEVICE_TYPES

router = APIRouter()


def _check(request: Request):
    if not request.session.get("user_id"):
        raise HTTPException(status_code=302, headers={"Location": "/login"})


class TopologyData(BaseModel):
    nodes: list
    edges: list
    shapes: list = []


@router.get("/topology", response_class=HTMLResponse)
def topology_page(request: Request):
    _check(request)
    devices = crud.get_all_devices(active_only=True)
    return templates.TemplateResponse("topology.html", {
        "request": request,
        "devices": devices,
        "device_types": DEVICE_TYPES,
        "username": request.session.get("username"),
    })


@router.get("/api/topology")
def api_get_topology(request: Request):
    _check(request)
    data = crud.get_topology()
    enriched = []
    for node in data.get("nodes", []):
        device = crud.get_device(node["device_id"])
        if device:
            enriched.append({
                "device_id": device["id"],
                "x": node.get("x", 100),
                "y": node.get("y", 100),
                "device": {
                    "id": device["id"], "name": device["name"],
                    "ip_address": device["ip_address"],
                    "device_type": device["device_type"],
                    "status": device["status"],
                    "icon_name": device["icon_name"],
                },
            })
    data["nodes"] = enriched
    return data


@router.post("/api/topology")
def api_save_topology(request: Request, payload: TopologyData):
    _check(request)
    crud.save_topology(json.dumps({"nodes": payload.nodes, "edges": payload.edges, "shapes": payload.shapes}))
    return {"ok": True}


@router.get("/api/topology/devices")
def api_topology_devices(request: Request):
    _check(request)
    data = crud.get_topology()
    placed_ids = {n["device_id"] for n in data.get("nodes", [])}
    devices = crud.get_all_devices(active_only=True)
    return [
        {
            "id": d["id"], "name": d["name"], "ip_address": d["ip_address"],
            "device_type": d["device_type"], "status": d["status"],
            "icon_name": d["icon_name"], "on_map": d["id"] in placed_ids,
        }
        for d in devices
    ]
