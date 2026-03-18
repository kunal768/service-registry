from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, HttpUrl


class RegisterRequest(BaseModel):
    service: str = Field(min_length=1, examples=["echo-service"])
    address: HttpUrl = Field(examples=["http://localhost:8001"])


class DeregisterRequest(BaseModel):
    service: str = Field(min_length=1, examples=["echo-service"])
    address: HttpUrl = Field(examples=["http://localhost:8001"])


@dataclass(frozen=True)
class InstanceView:
    address: str
    registered_at: datetime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


app = FastAPI(title="Service Registry", version="1.0.0")

# registry: service_name -> list of instances
_registry: Dict[str, List[InstanceView]] = {}
_lock = Lock()


@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": utc_now().isoformat()}


@app.post("/register", status_code=201)
def register(req: RegisterRequest):
    service = req.service.strip()
    address = str(req.address)

    if not service:
        raise HTTPException(status_code=400, detail="service is required")

    with _lock:
        instances = _registry.setdefault(service, [])
        existing = next((i for i in instances if i.address == address), None)
        if existing is not None:
            return {
                "status": "updated",
                "message": f"Service {service} at {address} already registered",
            }

        instances.append(InstanceView(address=address, registered_at=utc_now()))

    return {"status": "registered", "message": f"Service {service} registered at {address}"}


@app.post("/deregister")
def deregister(req: DeregisterRequest):
    service = req.service.strip()
    address = str(req.address)

    if not service:
        raise HTTPException(status_code=400, detail="service is required")

    with _lock:
        if service not in _registry:
            raise HTTPException(status_code=404, detail=f"Service {service} not found")

        before = len(_registry[service])
        _registry[service] = [i for i in _registry[service] if i.address != address]
        after = len(_registry[service])

        if after == 0:
            del _registry[service]

        if before == after:
            raise HTTPException(
                status_code=404, detail=f"Instance {address} not found for service {service}"
            )

    return {"status": "deregistered", "message": f"Service {service} at {address} deregistered"}


@app.get("/discover/{service}")
def discover(service: str):
    service = service.strip()
    if not service:
        raise HTTPException(status_code=400, detail="service is required")

    with _lock:
        instances = list(_registry.get(service, []))

    now = utc_now()
    payload_instances = [
        {
            "address": i.address,
            "uptime_seconds": (now - i.registered_at).total_seconds(),
        }
        for i in instances
    ]

    if not payload_instances:
        raise HTTPException(status_code=404, detail="Service not found")

    return {
        "service": service,
        "instances": payload_instances,
        "count": len(payload_instances),
    }


@app.get("/services")
def list_services():
    with _lock:
        services = {name: {"total_instances": len(instances)} for name, instances in _registry.items()}

    return {"services": services, "total_services": len(services)}

