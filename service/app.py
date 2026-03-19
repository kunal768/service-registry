from __future__ import annotations

import os
import time
from threading import Event, Thread
from typing import Optional
from uuid import uuid4

import requests
from fastapi import FastAPI


def env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v not in (None, "") else default


SERVICE_NAME = env("SERVICE_NAME", "echo-service")
INSTANCE_ID = env("INSTANCE_ID", str(uuid4())[:8])
PORT = int(env("PORT", "8001"))
REGISTRY_URL = env("REGISTRY_URL", "http://service-registry:5001")

# In Kubernetes, discoverability requires a reachable address.
# We use the pod IP when available.
POD_IP = os.getenv("POD_IP")
SELF_ADDRESS = (
    f"http://{POD_IP}:{PORT}" if POD_IP else env("SELF_ADDRESS", f"http://localhost:{PORT}")
)

REGISTER_RETRIES = int(env("REGISTER_RETRIES", "30"))
REGISTER_RETRY_DELAY_SECONDS = float(env("REGISTER_RETRY_DELAY_SECONDS", "0.5"))
HEARTBEAT_INTERVAL_SECONDS = float(env("HEARTBEAT_INTERVAL_SECONDS", "10"))


app = FastAPI(title=f"{SERVICE_NAME} ({INSTANCE_ID})", version="1.0.0")

_stop_event = Event()
_heartbeat_thread: Thread | None = None


def register_with_registry() -> bool:
    try:
        r = requests.post(
            f"{REGISTRY_URL}/register",
            json={"service": SERVICE_NAME, "address": SELF_ADDRESS},
            timeout=2,
        )
        return r.status_code in (200, 201)
    except Exception:
        return False


def deregister_from_registry() -> None:
    try:
        requests.post(
            f"{REGISTRY_URL}/deregister",
            json={"service": SERVICE_NAME, "address": SELF_ADDRESS},
            timeout=2,
        )
    except Exception:
        pass


def send_heartbeat_once() -> bool:
    try:
        r = requests.post(
            f"{REGISTRY_URL}/heartbeat",
            json={"service": SERVICE_NAME, "address": SELF_ADDRESS},
            timeout=2,
        )
        return r.status_code == 200
    except Exception:
        return False


def heartbeat_loop() -> None:
    # Periodically notify the registry so instances are considered alive.
    while not _stop_event.is_set():
        send_heartbeat_once()
        _stop_event.wait(HEARTBEAT_INTERVAL_SECONDS)


@app.on_event("startup")
def on_startup():
    ok = False
    for _ in range(max(1, REGISTER_RETRIES)):
        if register_with_registry():
            ok = True
            break
        time.sleep(REGISTER_RETRY_DELAY_SECONDS)

    if not ok:
        # Keep serving even if registry is down; client discovery will fail until registry is up.
        pass

    global _heartbeat_thread
    _heartbeat_thread = Thread(target=heartbeat_loop, daemon=True)
    _heartbeat_thread.start()


@app.on_event("shutdown")
def on_shutdown():
    _stop_event.set()
    deregister_from_registry()


@app.get("/health")
def health():
    return {"status": "healthy", "service": SERVICE_NAME, "instance_id": INSTANCE_ID, "port": PORT}


@app.get("/ping")
def ping():
    return {
        "service": SERVICE_NAME,
        "instance_id": INSTANCE_ID,
        "port": PORT,
        "message": "pong from a random instance",
    }


@app.get("/work")
def work(caller: Optional[str] = None):
    return {
        "service": SERVICE_NAME,
        "instance_id": INSTANCE_ID,
        "port": PORT,
        "message": "hello from a random instance",
        "caller": caller,
    }

