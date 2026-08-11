"""
OpenML control-dashboard — a minimal, purpose-built console to turn ML stacks
on/off and watch their resource use. Localhost-only, no auth by design.

Design note: a SINGLE background poller refreshes a shared snapshot of docker
status + stats every few seconds. All HTTP handlers read that cached snapshot,
so no request ever blocks on the docker socket — /api/stacks and the SSE stream
are instant regardless of how many browser tabs are open.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pathlib import Path

from . import docker_ctl as dc
from .stacks import CONTAINER_NAME, STACKS

STATIC = Path(__file__).resolve().parent.parent / "static"
POLL_SECONDS = 3

# shared snapshot, refreshed by the single background poller
SNAPSHOT: dict = {"status": {}, "stats": {}, "vm": 0, "ts": 0.0}


def _refresh_blocking() -> dict:
    """Runs in a thread — the only place that touches the docker socket on a timer."""
    return {
        "status": dc.list_managed(),
        "stats": dc.live_stats(),
        "vm": dc.vm_mem_bytes(),
        "ts": time.time(),
    }


async def _refresh() -> None:
    loop = asyncio.get_event_loop()
    snap = await loop.run_in_executor(None, _refresh_blocking)
    SNAPSHOT.update(snap)


async def _poller() -> None:
    while True:
        try:
            await _refresh()
        except Exception:  # never let the poller die
            pass
        await asyncio.sleep(POLL_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    with contextlib.suppress(Exception):
        await _refresh()          # warm the cache before serving
    task = asyncio.create_task(_poller())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="OpenML Console", docs_url="/api/docs", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# snapshot -> payloads  (no docker calls here)
# --------------------------------------------------------------------------- #
def _live_services() -> dict:
    status, stats = SNAPSHOT["status"], SNAPSHOT["stats"]
    out = {}
    for svc, info in status.items():
        live = stats.get(info.get("name", ""), {})
        out[svc] = {
            "status": info.get("status"),
            "health": info.get("health"),
            "cpu_pct": live.get("cpu_pct", 0.0),
            "mem_bytes": live.get("mem_bytes", 0.0),
        }
    return out


def _used_mem() -> float:
    return sum(v.get("mem_bytes", 0.0) for v in SNAPSHOT["stats"].values())


def _stack_by_key(key: str) -> dict:
    for s in STACKS:
        if s["key"] == key:
            return s
    raise HTTPException(status_code=404, detail=f"unknown stack: {key}")


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
@app.get("/")
def index() -> FileResponse:
    # no-cache so a rebuilt console never serves a stale page from the browser
    return FileResponse(STATIC / "index.html",
                        headers={"Cache-Control": "no-store"})


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    """Prometheus exposition of per-container CPU/mem from the cached snapshot.

    Reliable on Docker Desktop where cAdvisor cannot resolve container names.
    Metrics carry name/service/stack labels so Grafana can break down by service.
    """
    status, stats, vm = SNAPSHOT["status"], SNAPSHOT["stats"], SNAPSHOT["vm"]
    lines = [
        "# HELP openml_container_up 1 if the container is running",
        "# TYPE openml_container_up gauge",
    ]
    up, cpu, mem = [], [], []
    for svc, info in status.items():
        name = info.get("name", svc)
        stack = info.get("stack", "")
        lbl = f'name="{name}",service="{svc}",stack="{stack}"'
        running = 1 if info.get("status") == "running" else 0
        up.append(f"openml_container_up{{{lbl}}} {running}")
        live = stats.get(name, {})
        cpu.append(f"openml_container_cpu_percent{{{lbl}}} {live.get('cpu_pct', 0.0)}")
        mem.append(f"openml_container_mem_bytes{{{lbl}}} {int(live.get('mem_bytes', 0.0))}")
    lines += up
    lines += ["# HELP openml_container_cpu_percent container CPU usage percent",
              "# TYPE openml_container_cpu_percent gauge", *cpu]
    lines += ["# HELP openml_container_mem_bytes container memory usage bytes",
              "# TYPE openml_container_mem_bytes gauge", *mem]
    lines += ["# HELP openml_vm_mem_bytes docker VM total memory bytes",
              "# TYPE openml_vm_mem_bytes gauge", f"openml_vm_mem_bytes {int(vm)}",
              "# HELP openml_vm_mem_used_bytes memory used by OpenML containers",
              "# TYPE openml_vm_mem_used_bytes gauge",
              f"openml_vm_mem_used_bytes {int(_used_mem())}"]
    return PlainTextResponse("\n".join(lines) + "\n")


@app.get("/api/stacks")
def api_stacks() -> JSONResponse:
    """Full structure + current (cached) status/stats — instant, no docker calls."""
    status, stats = SNAPSHOT["status"], SNAPSHOT["stats"]
    stacks_out = []
    for s in STACKS:
        svc_out = []
        running = 0
        for svc in s["services"]:
            st = status.get(svc, {})
            cname = st.get("name") or CONTAINER_NAME.get(svc, f"openml-{svc}")
            live = stats.get(cname, {})
            if st.get("status") == "running":
                running += 1
            svc_out.append({
                "name": svc, "container": cname,
                "status": st.get("status", "absent"),
                "health": st.get("health"),
                "cpu_pct": live.get("cpu_pct", 0.0),
                "mem_bytes": live.get("mem_bytes", 0.0),
                "protected": svc in dc.PROTECTED,
            })
        stacks_out.append({
            "key": s["key"], "title": s["title"], "phase": s["phase"],
            "available": s["available"], "always_on": s["always_on"],
            "description": s["description"], "links": s["links"],
            "services": svc_out, "running": running, "total": len(s["services"]),
        })
    return JSONResponse({
        "stacks": stacks_out,
        "services": _live_services(),          # flat map for the live patcher
        "vm_mem_bytes": SNAPSHOT["vm"],
        "used_mem_bytes": _used_mem(),
    })


@app.post("/api/stack/{key}/up")
def api_stack_up(key: str) -> dict:
    s = _stack_by_key(key)
    if not s["available"]:
        raise HTTPException(status_code=409, detail=f"{key} arrives in phase {s['phase']}")
    ok, log = dc.stack_up(s["services"])
    return {"ok": ok, "log": log}


@app.post("/api/stack/{key}/down")
def api_stack_down(key: str) -> dict:
    s = _stack_by_key(key)
    if s["always_on"]:
        raise HTTPException(status_code=409, detail="core stack cannot be stopped")
    ok, log = dc.stack_stop(s["services"])
    return {"ok": ok, "log": log}


@app.post("/api/service/{service}/{action}")
def api_service_action(service: str, action: str) -> dict:
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(status_code=400, detail="action must be start|stop|restart")
    if service in dc.PROTECTED:
        raise HTTPException(
            status_code=409,
            detail=f"{service} runs this console and can't be controlled from here "
                   f"(use `docker compose restart {service}` from a terminal)",
        )
    ok, log = dc.service_action(service, action)
    return {"ok": ok, "log": log}


@app.get("/api/stream/stats")
async def api_stream_stats() -> StreamingResponse:
    """SSE: push the cached snapshot every ~2s. No docker calls per client."""
    async def gen():
        last = None
        while True:
            payload = {
                "services": _live_services(),
                "vm_mem_bytes": SNAPSHOT["vm"],
                "used_mem_bytes": _used_mem(),
            }
            blob = json.dumps(payload)
            if blob != last:                    # only send on change
                last = blob
                yield f"data: {blob}\n\n"
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
