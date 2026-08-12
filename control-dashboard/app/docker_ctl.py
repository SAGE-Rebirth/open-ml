"""
Thin control layer over the Docker daemon.

- Listing / status  -> docker-py (clean objects)
- Live stats        -> `docker stats --no-stream` (reliable, ready-computed)
- Stack up/stop     -> `docker compose ...` run in OPENML_PROJECT_DIR
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Optional

import docker

PROJECT_DIR = os.environ.get("OPENML_PROJECT_DIR", "/project")
PROJECT_NAME = os.environ.get("COMPOSE_PROJECT_NAME", "openml")
_MANAGED = {"label": "openml.managed=true"}

_client: Optional[docker.DockerClient] = None


def client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


# --------------------------------------------------------------------------- #
# status / listing
# --------------------------------------------------------------------------- #
def list_managed() -> dict[str, dict]:
    """Return {compose_service_name: {status, health, id, name}} for our containers."""
    out: dict[str, dict] = {}
    for c in client().containers.list(all=True, filters=_MANAGED):
        labels = c.labels or {}
        svc = labels.get("openml.service") or labels.get(
            "com.docker.compose.service"
        )
        if not svc:
            continue
        state = c.attrs.get("State", {}) or {}
        health = (state.get("Health") or {}).get("Status")  # may be None
        out[svc] = {
            "id": c.short_id,
            "name": c.name,
            "status": c.status,               # running | exited | created | ...
            "health": health,                 # healthy | unhealthy | starting | None
            "stack": labels.get("openml.stack"),
            "exit_code": state.get("ExitCode"),  # for one-shot setup jobs
        }
    return out


def vm_mem_bytes() -> int:
    try:
        total = int(client().info().get("MemTotal", 0))
    except Exception:
        total = 0
    if total <= 0:
        # fall back to the operator-declared VM size when the daemon doesn't report it
        try:
            total = int(float(os.environ.get("OPENML_VM_MEM_GB", "0")) * 1024**3)
        except ValueError:
            total = 0
    return total


# services the console must never stop/restart on itself
PROTECTED = {"control-dashboard"}


# --------------------------------------------------------------------------- #
# live stats  (docker stats --no-stream, parsed)
# --------------------------------------------------------------------------- #
_UNITS = {"B": 1, "KB": 1e3, "KiB": 1024, "MB": 1e6, "MiB": 1024**2,
          "GB": 1e9, "GiB": 1024**3, "TB": 1e12, "TiB": 1024**4}


def _to_bytes(text: str) -> float:
    text = text.strip()
    for unit in ("TiB", "GiB", "MiB", "KiB", "TB", "GB", "MB", "KB", "B"):
        if text.endswith(unit):
            try:
                return float(text[: -len(unit)]) * _UNITS[unit]
            except ValueError:
                return 0.0
    return 0.0


def live_stats() -> dict[str, dict]:
    """{container_name: {cpu_pct, mem_bytes}} for all running managed containers."""
    running = [
        c.name for c in client().containers.list(filters=_MANAGED)
    ]
    if not running:
        return {}
    try:
        proc = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}", *running],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}
    stats: dict[str, dict] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        mem_usage = (row.get("MemUsage") or "0B / 0B").split("/")[0]
        cpu = (row.get("CPUPerc") or "0%").rstrip("%")
        try:
            cpu_pct = float(cpu)
        except ValueError:
            cpu_pct = 0.0
        stats[row.get("Name", "")] = {
            "cpu_pct": cpu_pct,
            "mem_bytes": _to_bytes(mem_usage),
        }
    return stats


# --------------------------------------------------------------------------- #
# lifecycle
# --------------------------------------------------------------------------- #
def _compose(*args: str) -> tuple[bool, str]:
    cmd = ["docker", "compose", "-p", PROJECT_NAME, *args]
    try:
        proc = subprocess.run(
            cmd, cwd=PROJECT_DIR, capture_output=True, text=True, timeout=600
        )
    except subprocess.TimeoutExpired:
        return False, "timed out"
    ok = proc.returncode == 0
    return ok, (proc.stdout + proc.stderr).strip()[-4000:]


def stack_up(services: list[str]) -> tuple[bool, str]:
    # naming services explicitly enables their profile
    return _compose("up", "-d", "--build", *services)


def stack_stop(services: list[str]) -> tuple[bool, str]:
    # `stop` keeps containers (fast restart) but frees their RAM
    return _compose("stop", *services)


def service_action(service: str, action: str) -> tuple[bool, str]:
    if action == "start":
        return _compose("up", "-d", service)
    if action == "stop":
        return _compose("stop", service)
    if action == "restart":
        return _compose("restart", service)
    return False, f"unknown action: {action}"
