from __future__ import annotations

import os
import time
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
REGISTRY_URL = env("REGISTRY_URL", "http://localhost:5001")
SELF_ADDRESS = env("SELF_ADDRESS", f"http://localhost:{PORT}")

REGISTER_RETRIES = int(env("REGISTER_RETRIES", "30"))
REGISTER_RETRY_DELAY_SECONDS = float(env("REGISTER_RETRY_DELAY_SECONDS", "0.5"))


app = FastAPI(title=f"{SERVICE_NAME} ({INSTANCE_ID})", version="1.0.0")


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


@app.on_event("shutdown")
def on_shutdown():
    deregister_from_registry()


@app.get("/health")
def health():
    return {"status": "healthy", "service": SERVICE_NAME, "instance_id": INSTANCE_ID, "port": PORT}


@app.get("/work")
def work(caller: Optional[str] = None):
    return {
        "service": SERVICE_NAME,
        "instance_id": INSTANCE_ID,
        "port": PORT,
        "message": "hello from a random instance",
        "caller": caller,
    }

