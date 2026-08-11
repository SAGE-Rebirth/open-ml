# Reliability & failure modes

How OpenML behaves under crashes, restarts, locks and resource pressure, and
the trade-offs accepted for a single-machine personal platform.

## Handled

- **Auto-recovery from crashes** — every long-running service uses
  `restart: unless-stopped`; one-shot jobs (`db-init`, `minio-init`) use
  `restart: "no"`. A crashed service comes back on its own.
- **Startup ordering** — services that need Postgres/MinIO wait on
  `depends_on: condition: service_healthy`.
- **Console never blocks** — a single background poller refreshes a cached
  snapshot; all HTTP handlers read the cache, so the docker socket can never
  wedge `/api/stacks` or the SSE stream. The poller swallows all exceptions and
  never dies. SSE auto-reconnects.
- **Telemetry is best-effort** — `openml_telemetry` wraps every MLflow / Aim /
  Pushgateway call in try/except, so training continues even if the track/
  monitor stacks are off.
- **Memory blast-radius** — the notebook container is capped
  (`JUPYTER_MEM_LIMIT`, default 4g) so a runaway job kills only its own kernel
  instead of OOMing the VM and taking down core services.
- **No stale live-metrics** — a training run deletes its Pushgateway group on
  exit; the full history remains in Prometheus (7-day TSDB) and MLflow/Aim.
- **Console footguns removed** — it refuses to stop/restart *itself*, and core
  infra (postgres/minio/redis) is restart-only from the UI.
- **Idempotent init** — `db-init` and `minio-init` are safe to re-run.

## Known risks & accepted trade-offs

| Area | Risk | Severity | Mitigation |
|---|---|---|---|
| Storage | Postgres/MinIO are single-node with no backups | med | personal use; `docker run` a dump if data matters. Volumes persist across restarts. |
| Runtime deps | Postgres/MinIO down → MLflow/LabelStudio/etc. error until it returns | low | apps reconnect automatically; transient only |
| Aim | server + UI share one container; if the background `aim server` dies, logging degrades silently (UI stays up) | low | helper catches it; `docker compose restart aim` |
| Aim | hard-kill mid-write can leave a RocksDB lock in the repo | low | only one process uses the repo, so `restart aim` clears it |
| MLflow | a hard-killed kernel leaves the run stuck `RUNNING` | low | context-manager marks FAILED on exceptions; hard kills are rare |
| Disk | Prometheus (bounded 7d), MinIO/Postgres, build cache grow over time | low | `docker system prune`; watch disk |
| Other containers | no memory limits besides Jupyter | low | footprints are small and stable; add `mem_limit` if needed |
| Security | no auth, default creds | by design | bound to `127.0.0.1`; see README security |

## Recovery cheatsheet

```bash
make ps                       # what's up / restart counts
docker logs openml-<svc>      # why something failed
docker compose restart <svc>  # bounce one service
make stop && make up          # clean bounce of everything (keeps data)
make nuke                     # last resort: wipe containers AND volumes
```
