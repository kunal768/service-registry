from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
import time
from threading import Lock, Thread
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, HttpUrl


class RegisterRequest(BaseModel):
    service: str = Field(min_length=1, examples=["echo-service"])
    address: HttpUrl = Field(examples=["http://localhost:8001"])

class HeartbeatRequest(BaseModel):
    service: str = Field(min_length=1, examples=["echo-service"])
    address: HttpUrl = Field(examples=["http://localhost:8001"])


class DeregisterRequest(BaseModel):
    service: str = Field(min_length=1, examples=["echo-service"])
    address: HttpUrl = Field(examples=["http://localhost:8001"])


@dataclass
class InstanceView:
    address: str
    registered_at: datetime
    last_heartbeat: datetime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_address(address: str) -> str:
    # Prevent duplicates from minor formatting differences (e.g., trailing '/').
    a = (address or "").strip()
    return a.rstrip("/")


# Health/TTL configuration. In Kubernetes, the registry must evict dead pods.
HEARTBEAT_TIMEOUT_SECONDS = int(os.getenv("HEARTBEAT_TIMEOUT_SECONDS", "30"))
CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "10"))


app = FastAPI(title="Service Registry", version="1.0.0")

# registry: service_name -> list of instances
_registry: Dict[str, List[InstanceView]] = {}
_lock = Lock()
_cleanup_thread_started = False


@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": utc_now().isoformat()}


@app.post("/register", status_code=201)
def register(req: RegisterRequest):
    service = req.service.strip()
    address = normalize_address(str(req.address))

    if not service:
        raise HTTPException(status_code=400, detail="service is required")

    with _lock:
        instances = _registry.setdefault(service, [])
        existing = next((i for i in instances if i.address == address), None)
        if existing is not None:
            # Re-registering counts as a heartbeat to keep the entry alive.
            existing.last_heartbeat = utc_now()
            return {
                "status": "updated",
                "message": f"Service {service} at {address} heartbeat updated",
            }

        now = utc_now()
        instances.append(InstanceView(address=address, registered_at=now, last_heartbeat=now))

    return {"status": "registered", "message": f"Service {service} registered at {address}"}


@app.post("/heartbeat")
def heartbeat(req: HeartbeatRequest):
    service = req.service.strip()
    address = normalize_address(str(req.address))

    if not service:
        raise HTTPException(status_code=400, detail="service is required")

    with _lock:
        if service not in _registry:
            raise HTTPException(status_code=404, detail=f"Service {service} not found")

        instance = next((i for i in _registry[service] if i.address == address), None)
        if instance is None:
            raise HTTPException(
                status_code=404,
                detail=f"Instance {address} not found for service {service}",
            )

        instance.last_heartbeat = utc_now()

    return {"status": "ok", "message": "Heartbeat updated"}


@app.post("/deregister")
def deregister(req: DeregisterRequest):
    service = req.service.strip()
    address = normalize_address(str(req.address))

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
    active_instances = [
        i
        for i in instances
        if (now - i.last_heartbeat).total_seconds() < HEARTBEAT_TIMEOUT_SECONDS
    ]

    if not active_instances:
        raise HTTPException(status_code=404, detail="Service not found")

    return {
        "service": service,
        "instances": [
            {
                "address": i.address,
                "uptime_seconds": (now - i.registered_at).total_seconds(),
            }
            for i in active_instances
        ],
        "count": len(active_instances),
    }


@app.get("/services")
def list_services():
    now = utc_now()
    with _lock:
        services: Dict[str, Dict[str, int]] = {}
        for name, instances in _registry.items():
            active_count = sum(
                1
                for i in instances
                if (now - i.last_heartbeat).total_seconds() < HEARTBEAT_TIMEOUT_SECONDS
            )
            services[name] = {"total_instances": len(instances), "active_instances": active_count}

    return {"services": services, "total_services": len(services)}


def cleanup_stale_instances_forever() -> None:
    # Background task that evicts instances that have stopped sending heartbeats.
    while True:
        time.sleep(CLEANUP_INTERVAL_SECONDS)
        now = utc_now()

        with _lock:
            services_to_delete: List[str] = []
            for service, instances in _registry.items():
                active_instances = [
                    i
                    for i in instances
                    if (now - i.last_heartbeat).total_seconds() < HEARTBEAT_TIMEOUT_SECONDS
                ]

                if active_instances:
                    _registry[service] = active_instances
                else:
                    services_to_delete.append(service)

            for service in services_to_delete:
                del _registry[service]


@app.on_event("startup")
def start_cleanup_thread():
    global _cleanup_thread_started
    if _cleanup_thread_started:
        return
    _cleanup_thread_started = True
    Thread(target=cleanup_stale_instances_forever, daemon=True).start()

