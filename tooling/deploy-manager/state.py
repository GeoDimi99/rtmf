"""
What the deploy-manager keeps in Redis next to the plan:

    rtmo:lock      held during an apply, so two applies never run at once
    rtmo:applied   what is running: implementation, manifest, RTMO version, time, status
"""

import socket
import time
from typing import Dict, Optional

LOCK_KEY = "rtmo:lock"
APPLIED_KEY = "rtmo:applied"
LOCK_SECONDS = 600


class LockedError(Exception):
    pass


class ApplyLock:
    def __init__(self, client):
        self.client = client
        self.owner = f"{socket.gethostname()}:{time.time():.0f}"

    def __enter__(self):
        if not self.client.set(LOCK_KEY, self.owner, nx=True, ex=LOCK_SECONDS):
            raise LockedError(f"another apply is running ({self.client.get(LOCK_KEY)}); "
                              f"if not, delete the Redis key {LOCK_KEY}")
        return self

    def __exit__(self, *exc):
        if self.client.get(LOCK_KEY) == self.owner:
            self.client.delete(LOCK_KEY)
        return False


def clear_plan(client) -> None:
    """Remove the previous plan; only the rtmo:* keys survive (as a fresh Redis did before)."""
    for key in list(client.scan_iter()):
        if not key.startswith("rtmo:"):
            client.delete(key)


def record(client, profile: str, manifest: str, digest: Optional[str], version: str) -> None:
    client.delete(APPLIED_KEY)
    client.hset(APPLIED_KEY, mapping={
        "profile": profile,
        "manifest": manifest,
        "manifest_digest": digest or "",
        "rtmo_version": version,
        "applied_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": "running",
    })


def mark_stopped(client) -> None:
    if client.hgetall(APPLIED_KEY):
        client.hset(APPLIED_KEY, mapping={"status": "stopped", "stopped_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})


def read(client) -> Dict[str, str]:
    return client.hgetall(APPLIED_KEY)
