# CLAUDE.md — OpenML

Guidance for working in this repo. **Read this fully before making changes** — it
is the onboarding doc for a fresh session.

## What this is

**OpenML** is a personal, local-first MLOps platform — "SageMaker/Vertex-at-home"
— that runs the full ML lifecycle on a single **Apple M4 / 24 GB** machine via
**Docker Compose**, with a **custom control-dashboard** ("the console") to turn
each stack on/off. Long-term goal: polish into an open-source project.

## Status — you are here (2026-08-12)

**Phases 0–5 complete, verified running. Phase 6 (vision) is the only one left.**

| Phase | Stack | What it added | Done |
|---|---|---|---|
| 0 | core + develop | console, Postgres, MinIO, Redis, JupyterLab | ✅ |
| 1 | track + monitor | MLflow+Aim, Prometheus/Grafana/cAdvisor/node-exporter/pushgateway, telemetry helper | ✅ |
| 2 | label | Label Studio + DVC→MinIO | ✅ |
| 3 | pipeline | ZenML (native arm64), example pipeline | ✅ |
| 4 | cicd | Gitea + Actions, train-on-push | ✅ |
| 5 | serve | BentoML inference + Gradio playground, from MLflow registry | ✅ |
| 6 | vision | host camera-bridge (MJPEG/RTSP+Redis) + container consumer | ⏳ **next** |

Plus (not phases): **Secrets Vault** (multi-vault, project-scoped, in the console),
a **Setup-jobs** strip in the console, and a full SRE audit pass (mem-caps on all
containers, all volumes compose-managed, disk pruned). Full plan:
`~/.claude/plans/bright-cooking-seahorse.md`.

## First steps in a NEW session

1. **Check Docker Desktop is running** — it has quit mid-session before (Mac
   sleep). If `docker ps` errors with a missing socket: `open -a Docker`, wait
   ~30–60 s for the daemon.
2. **Containers do NOT auto-start after Docker Desktop restarts** (they're
   `restart: unless-stopped`, but a full Desktop quit leaves them `Exited`).
   Bring them back: `make up` (core), then start the stacks you need, e.g.
   `docker compose up -d jupyter mlflow aim prometheus grafana cadvisor node-exporter pushgateway`.
   **Data always survives** — everything is in named volumes.
3. **Health sweep before trusting anything:**
   `docker ps --filter label=openml.managed=true` — want all `healthy`, 0 restarts.
4. Open the console at **http://localhost:8080** and toggle stacks from there.

## Hard platform constraints (design is shaped around these — don't fight them)

Docker Desktop on macOS runs Linux in a VM. Two non-negotiable limits:

1. **No USB / camera passthrough into containers.** The Mac camera is bridged
   from the host (Phase 6), never `--device` into a container.
2. **No Apple GPU (MPS/Metal) inside containers.** GPU-heavy training runs
   **natively on the host** against the same MLflow/MinIO endpoints; containers
   do orchestration, tracking, serving, and CPU work. `torch` in a container is
   CPU-only.

Consequence: **RAM is the budget.** Give the Docker VM ~12–14 GB and use Compose
**profiles** so only the stacks you're using run. That's why the console exists.

## Golden rules

1. **Everything lives in `docker-compose.yml`.** No independent `docker build`,
   `docker run`, or `docker volume create`. Any image the platform needs → a
   compose service with a `build:` context (even build-only helpers that run
   `command: ["true"]`, e.g. `ci-runner`). Any volume → declared in the compose
   `volumes:` block. Verify: `docker volume inspect <v>` must show
   `com.docker.compose.project=openml`. (The one unavoidable exception is Gitea
   Actions **job containers**, spawned per-job by the runner — labeled
   `openml.project=openml`/`openml.stack=cicd-job` via `cicd/runner-config.yaml`.)
2. **Verify against the running system, SRE-style.** Measure before changing
   (e.g. `pip install --dry-run` before adding deps), then prove each change
   end-to-end with real values — not "looks right". Every phase ended with a
   health sweep (all healthy, 0 restarts, data intact).
3. **Localhost-only.** Host ports bind to `127.0.0.1` via `${BIND_HOST}`. No auth
   by design; never expose ports without adding auth + changing default creds.
4. **Memory limits on every container** (`mem_limit`) so a runaway kills only
   itself, not the VM.
5. **Keep docs in sync.** When you finish a phase/feature, update the Status
   table above, the relevant `docs/*.md`, README, and the memory files.

## Running it

Always use `make` from the repo root (it exports `OPENML_PROJECT_DIR=$(pwd)`,
which the console needs to run `docker compose` from inside its container).

```
make up        # start CORE (postgres, minio, redis, control-dashboard) + build
make develop   # start JupyterLab
make ps        # status of everything (all profiles)
make logs S=jupyter
make stop      # stop containers, keep data
make down      # remove containers, keep volumes
make prune     # reclaim disk (build cache, dangling images, unused volumes)
make nuke      # DANGER: remove containers AND volumes
make config    # validate merged compose config
```

The console starts a stack with `docker compose up -d --build <services>` and
stops it with `docker compose stop <services>` (per `control-dashboard/app/docker_ctl.py`).
First run: `cp .env.example .env` (the Makefile does this automatically).

## Services, ports, and default credentials

All ports bind to `127.0.0.1`; values live in `.env` (`.env.example` is the map).

| Service | Port | Login (change for non-local!) |
|---|---|---|
| console (control-dashboard) | 8080 | none |
| jupyter | 8888 | token `openml` |
| mlflow | 5000 | none |
| aim | 43800 (server 53800) | none |
| grafana | 3000 | `admin` / `admin` (+ anon viewer) |
| prometheus / cadvisor / node-exporter / pushgateway | 9090 / 8082 / 9100 / 9091 | none |
| label-studio | 8081 | `admin@openml.local` / `openml-admin` |
| zenml | 8237 | `NO_AUTH` (client uses `ZENML_STORE_URL`) |
| gitea | 3001 | `openml` / `openml-admin` |
| minio | 9000 (api) / 9001 (console) | `minioadmin` / `minioadmin123` |
| inference (BentoML) | 8000 | none |
| playground (Gradio) | 7860 | none |

Postgres: `openml`/`openml`, db `openml` + per-service dbs. Vault: **you set** a
passphrase per vault (nothing pre-provisioned).

## The console (`control-dashboard/`)

FastAPI + docker-py + a single vanilla-JS/CSS page (`static/index.html`, no
framework, no CDN).
- **One background poller** refreshes a cached snapshot; all HTTP handlers read
  the cache → the docker socket can never wedge `/api/stacks` or the SSE stream.
- Discovers containers by label `openml.managed=true`, groups by `openml.stack`
  (registry in `app/stacks.py`: `STACKS`, `CONTAINER_NAME`, `SETUP_JOBS`).
- Exposes `/metrics` (per-container CPU/mem with name labels) — the **reliable**
  source on Docker Desktop, where cAdvisor can't resolve container names.
- Hosts the **Secrets Vault** (`app/vault.py`, `/api/vault/*`) — see below.
- Mounts the docker socket + the project dir **at the same absolute path** as the
  host, so `docker compose` run inside resolves bind mounts/build contexts.
- Rebuild after editing `app/*.py` or `static/index.html`:
  `docker compose up -d --build control-dashboard`.

## Secrets Vault (in the console)

Envelope encryption: one random DEK per vault encrypts all secrets (AES-256-GCM);
the DEK is wrapped by multiple key slots (passphrase / access codes / recovery
key / optional auto-unseal) — any one unlocks. **Multiple named vaults**; each
secret is scoped `global` or to a **project name**. Storage = Postgres
(`vault_*` tables); DEK only in the dashboard process memory. CLI for other
projects: `cli/openml-secret` (pure stdlib). Never-locked-out nets: recovery key,
encrypted backup/restore, guarded reset. See `docs/vault.md`.

## Repo layout

```
docker-compose.yml         # single source of truth — all services + profiles
.env.example / Makefile
control-dashboard/         # the console (FastAPI + docker-py + static UI + vault)
  app/{main,docker_ctl,stacks,vault}.py · static/index.html
jupyter/ mlflow/ zenml/    # custom image build contexts
serving/{bentoml,fastapi,gradio}/   # Phase 5 serve images (bentoml=default, fastapi=example)
monitoring/                # prometheus.yml + grafana provisioning/dashboards (4 dashboards)
cicd/                      # ci-runner image, runner-config.yaml, demo-repo/
cli/openml-secret          # stdlib CLI for the vault (other projects)
notebooks/                 # demos (see below) + openml_telemetry.py helper
workspace/                 # shared bind-mount (jupyter + label-studio local files)
docs/                      # architecture, macos-constraints, reliability, labeling,
                           #   pipelines, cicd, serving, vault, memory-and-profiles
```

## Notebooks & demos (`notebooks/`)

- `00_minio_smoke_test.ipynb` — Phase 0: MinIO r/w, Postgres, Redis, torch(cpu).
- `01_training_telemetry.ipynb` — Phase 1: torch training → MLflow + Aim + live
  Grafana gauges (via `openml_telemetry.py`, which fans metrics to MLflow +
  Pushgateway + Aim and clears the pushgateway group on exit).
- `02_labeling_and_dvc.ipynb` — Phase 2: generate images → Label Studio (local
  storage) → DVC push to MinIO.
- `03_pipeline.ipynb` — Phase 3: ZenML `ingest→preprocess→train→evaluate→register`.
- Serving (Phase 5) has no notebook — use `curl :8000/predict` or the Gradio
  playground; the demo model `serve-demo` (sklearn iris, alias `@champion`) is
  registered via the snippet in `docs/serving.md`.

## Conventions

- **Every service** carries labels `openml.managed=true`, `openml.stack=<profile>`,
  `openml.service=<name>`; `container_name: openml-<service>`.
- **Adding a service:** give it a `profiles:` entry, the three labels,
  `restart: unless-stopped` (one-shots use `restart: "no"`), a healthcheck, a
  `mem_limit`, `${BIND_HOST}:` on published ports, a named volume for any path
  the image declares `VOLUME` on (else you get orphan anon volumes), and register
  it in `control-dashboard/app/stacks.py` (STACKS + CONTAINER_NAME). Add its port
  to `.env.example` and to the dashboard's `environment:` block (for link building).
- **One-shot init jobs** (`db-init`, `minio-init`, `gitea-init`, `ci-runner`):
  `Exited (0)` = success. They show in the console's "Setup jobs" strip.
- **Postgres** backs metadata; per-service DBs (`mlflow`, `labelstudio`, `zenml`,
  `gitea`) are created idempotently by `db-init`.
- **MinIO** is the S3 backbone (buckets `mlflow`, `datasets`, `models`).

## Hard-won gotchas (don't re-discover these)

- **cAdvisor on Docker Desktop** can't resolve container names (empty
  DockerVersion). Per-container Grafana panels use the dashboard's `/metrics`
  exporter (`openml_container_*`), not `container_*{name=...}`.
- **node-exporter**: `rslave` propagation on `/` is rejected by the VM → mount
  `/proc` + `/sys` read-only instead.
- **ZenML server image is amd64-only** → we build a native arm64 image; the
  client (`zenml==0.96.3` in jupyter) must match the server version. Server runs
  SQLite single-worker with `NO_AUTH`; `zenml/entrypoint.sh` seeds the default
  user (the app doesn't, so NO_AUTH otherwise 500s on a fresh DB). From a
  notebook, run `zenml init` first (no `__file__` for flavor source root); the
  MLflow tracker needs dummy creds for its remote URI.
- **Gitea Actions**: `generate-runner-token` hits Gitea's *internal* API — only
  works via `docker exec` into the running gitea (not a standalone CLI).
  act-runner registers via **env vars** (`GITEA_RUNNER_REGISTRATION_TOKEN_FILE`),
  not `--instance` flags. Job containers join `openml_net` via the runner config.
- **DVC 3.59** breaks on `pathspec` 1.x → pinned `pathspec==0.12.1`.
- **sklearn 1.6 vs MLflow autolog** — the Jupyter base ships scikit-learn 1.6.0;
  MLflow 2.19 autolog prints an "unsupported version (≤1.5.2)" *warning* but works.
  Left as-is on purpose (downgrading the base image risks conflicts); the
  `ci-runner` image pins 1.5.2. Monitor if a future MLflow/sklearn combo breaks.
- **Label Studio**: uses **Local Storage** on the shared `workspace` volume, not
  S3 — MinIO presigned URLs use the internal `minio` host the browser can't
  resolve (split-horizon).
- **BentoML on py3.12-slim**: its `fs` dep imports `pkg_resources`; slim doesn't
  ship it and **setuptools≥81 removed it** → pin `setuptools<81`. BentoML emits
  `bentoml_service_*` Prometheus metrics (the Serving dashboard uses those, not
  `openml_inference_*`). It serves `/predict` and `/metrics` on the same port.
- **Cross-profile `depends_on` breaks `up`**: e.g. `inference` (serve) must NOT
  `depends_on: mlflow` (track) — naming one service doesn't activate the other's
  profile → "no such service". Serve just requires Track to be on.
- **Image-declared `VOLUME` → orphan anon volumes**: redis/db-init got
  `project=none` anonymous volumes; give such services a named volume at that path
  (tmpfs does NOT prevent it in this Docker build).

## Locked architecture decisions

- **Serving:** BentoML default (`serving/bentoml/`) + a small FastAPI example
  (`serving/fastapi/`, emits `openml_inference_*`) + a **Gradio** playground;
  MLServer→KServe/Seldon documented as the cluster path.
- **Tracking:** MLflow (registry) + Aim only. No self-hosted W&B (heavy/licensed);
  W&B/Comet/Neptune are opt-in via ZenML.
- **Console:** stays custom (it's a real-time control plane; Gradio is for the
  serving playground, not the console).
- **Pluggability via ZenML** is the "generic for everyone" story — trackers and
  deployers are swappable stack components.

## Where to look

- Full phased plan: `~/.claude/plans/bright-cooking-seahorse.md`
- Per-topic docs in `docs/` (architecture, reliability, vault, cicd, pipelines,
  serving, labeling, macos-constraints, memory-and-profiles).
