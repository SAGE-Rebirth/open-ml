# CLAUDE.md — OpenML

Guidance for working in this repo. Read this before making changes.

## What this is

**OpenML** is a personal, local-first MLOps platform — "SageMaker/Vertex-at-home"
— that runs the full ML lifecycle on a single **Apple M4 / 24 GB** machine via
**Docker Compose**, with a **custom control-dashboard** ("the console") to turn
each stack on/off. Long-term goal: polish into an open-source project.

## Hard platform constraints (design is shaped around these — don't fight them)

Docker Desktop on macOS runs Linux in a VM. Two non-negotiable limits:

1. **No USB / camera passthrough into containers.** The Mac camera is bridged
   from the host (planned Phase 6), never `--device` into a container.
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
   Actions **job containers**, spawned per-job by the runner — they're labeled
   `openml.project=openml`/`openml.stack=cicd-job` via `cicd/runner-config.yaml`.)
2. **Verify against the running system, SRE-style.** Measure before changing
   (e.g. `pip install --dry-run` before adding deps), then prove each change
   end-to-end with real values — not "looks right". Every phase ended with a
   health sweep (all healthy, 0 restarts, data intact).
3. **Localhost-only.** Host ports bind to `127.0.0.1` via `${BIND_HOST}`. No auth
   by design; never expose ports without adding auth + changing default creds.
4. **Memory limits on user-code containers** (`mem_limit`) so a runaway job kills
   only itself, not the VM.

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
make nuke      # DANGER: remove containers AND volumes
make config    # validate merged compose config
```

Then open the console at **http://localhost:8080** and toggle stacks on/off.
First run: `cp .env.example .env` (the Makefile does this automatically).

## Architecture: stacks → Compose profiles

Services are grouped into **profiles**; the console toggles them. `core` has no
profile (always on). The console starts a stack with
`docker compose up -d --build <services>` and stops it with `stop`.

| Profile | Services | Maps to | Status |
|---|---|---|---|
| `core` *(always on)* | control-dashboard, postgres, minio(+init), redis, db-init | the Console + S3 + metadata DB | ✅ |
| `develop` | jupyter | Studio / Workbench | ✅ Phase 0 |
| `track` | mlflow, aim | Experiments + registry | ✅ Phase 1 |
| `monitor` | prometheus, grafana, cadvisor, node-exporter, pushgateway | Model Monitor / infra | ✅ Phase 1 |
| `label` | label-studio | Ground Truth | ✅ Phase 2 |
| `pipeline` | zenml | Pipelines | ✅ Phase 3 |
| `cicd` | gitea, gitea-init, act-runner, ci-runner | Projects / CI | ✅ Phase 4 |
| `serve` | inference (BentoML) + Gradio playground | Endpoints | ⏳ Phase 5 |
| `vision` | host camera-bridge + consumer | camera/OpenCV | ⏳ Phase 6 |

**Ports** (all `127.0.0.1`, in `.env`): console 8080 · jupyter 8888 · mlflow 5000
· aim 43800 · grafana 3000 · prometheus 9090 · cadvisor 8082 · pushgateway 9091 ·
label-studio 8081 · zenml 8237 · gitea 3001 · minio 9000/9001.

## The console (`control-dashboard/`)

FastAPI + docker-py + a single vanilla-JS/CSS page (no framework, no CDN).
- **One background poller** refreshes a cached snapshot; all HTTP handlers read
  the cache → the docker socket can never wedge `/api/stacks` or the SSE stream.
- Discovers containers by label `openml.managed=true`, groups by `openml.stack`.
- Exposes `/metrics` (per-container CPU/mem with name labels) — the **reliable**
  source on Docker Desktop, where cAdvisor can't resolve container names.
- Hosts the **Secrets Vault** (`app/vault.py`, `/api/vault/*`). See `docs/vault.md`.
- Mounts the docker socket + the project dir **at the same absolute path** as the
  host, so `docker compose` run inside resolves bind mounts/build contexts.

## Repo layout

```
docker-compose.yml         # single source of truth — all services + profiles
.env.example / Makefile
control-dashboard/         # the console (FastAPI + docker-py + static UI + vault)
jupyter/ mlflow/ zenml/    # custom image build contexts
monitoring/                # prometheus.yml + grafana provisioning/dashboards
cicd/                      # ci-runner image, runner-config.yaml, demo-repo/
cli/openml-secret          # stdlib CLI for the vault (other projects)
notebooks/                 # 00 smoke, 01 telemetry, 02 labeling+dvc, 03 pipeline
workspace/                 # shared bind-mount (jupyter + label-studio local files)
docs/                      # architecture, macos-constraints, reliability, labeling,
                           #   pipelines, cicd, vault, memory-and-profiles
```

## Conventions

- **Every service** carries labels `openml.managed=true`, `openml.stack=<profile>`,
  `openml.service=<name>`; `container_name: openml-<service>`.
- **Adding a service:** give it a `profiles:` entry, the three labels,
  `restart: unless-stopped` (one-shots use `restart: "no"`), a healthcheck, a
  `mem_limit` if it runs heavy/user code, `${BIND_HOST}:` on published ports, and
  register it in `control-dashboard/app/stacks.py` (STACKS + CONTAINER_NAME).
- **One-shot init jobs** (`db-init`, `minio-init`, `gitea-init`, `ci-runner`):
  `Exited (0)` = success. They appear in the console's "Setup jobs" strip.
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

## Locked architecture decisions

- **Serving (Phase 5):** BentoML default + a small FastAPI example + a **Gradio**
  playground; MLServer→KServe/Seldon documented as the cluster path.
- **Tracking:** MLflow (registry) + Aim only. No self-hosted W&B (heavy/licensed);
  W&B/Comet/Neptune are opt-in via ZenML.
- **Console:** stays custom (it's a real-time control plane; Gradio is for the
  serving playground, not the console).
- **Pluggability via ZenML** is the "generic for everyone" story — trackers and
  deployers are swappable stack components.

## Where to look

- Full phased plan: `~/.claude/plans/bright-cooking-seahorse.md`
- Per-topic docs in `docs/` (architecture, reliability, vault, cicd, pipelines,
  labeling, macos-constraints, memory-and-profiles).
