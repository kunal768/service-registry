from __future__ import annotations

import argparse
import random
import sys
import time
import os
from typing import Any, Dict, List, Tuple

import requests


def discover_instances(registry_url: str, service: str) -> List[Dict[str, Any]]:
    r = requests.get(f"{registry_url}/discover/{service}", timeout=3)
    if r.status_code != 200:
        raise RuntimeError(f"Discovery failed: {r.status_code} {r.text}")
    data = r.json()
    return data.get("instances", [])


def call_ping(instance_address: str, caller: str) -> Tuple[int, Dict[str, Any]]:
    # /ping is the simple "prove the client can call an instance" endpoint.
    r = requests.get(f"{instance_address}/ping", timeout=3)
    payload = (
        r.json()
        if r.headers.get("content-type", "").startswith("application/json")
        else {"raw": r.text}
    )
    # Include caller so it is obvious which client run triggered the request.
    if isinstance(payload, dict):
        payload.setdefault("caller", caller)
    return r.status_code, payload


def main() -> int:
    p = argparse.ArgumentParser(description="Discover a service and call a random instance.")
    p.add_argument("--registry-url", default=os.getenv("REGISTRY_URL", "http://localhost:5001"))
    p.add_argument("--service", default="echo-service")
    p.add_argument("--calls", type=int, default=5)
    p.add_argument("--delay-seconds", type=float, default=1.0)
    p.add_argument("--caller", default="client")
    args = p.parse_args()

    for i in range(args.calls):
        instances = discover_instances(args.registry_url, args.service)
        if not instances:
            raise RuntimeError(f"No instances found for service {args.service}")

        chosen = random.choice(instances)
        address = chosen["address"]

        status, payload = call_ping(address, caller=f"{args.caller}#{i+1}")
        print(f"[call {i+1}] discovered={len(instances)} chosen={address} status={status}")
        print(payload)

        if i + 1 < args.calls:
            time.sleep(args.delay_seconds)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)

