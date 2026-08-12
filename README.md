# OpenML — a personal, self-hosted ML platform

SageMaker/Vertex-style ML lifecycle on **one Apple Silicon Mac**, driven by
Docker Compose, with a **custom console** to turn each stack on/off so you
never blow past your RAM budget.

> **Status:** Phase 0 (core + JupyterLab). Later phases add telemetry,
> labeling, pipelines, CI/CD, serving, and a camera bridge — see
> [`docs/architecture.md`](docs/architecture.md) and the roadmap tiles that are
> already visible (greyed out) in the console.

## Quick start

```bash
make up          # start CORE: postgres, minio, redis, and the console
open http://localhost:8080          # the OpenML console
```

From the console, flip **Develop · JupyterLab** on, then:

```bash
open http://localhost:8888          # token: openml  (see .env)
```

Run `notebooks/00_minio_smoke_test.ipynb` to confirm the container can reach
MinIO, Postgres, Redis, and torch.

## What's available

**Phase 0 — core + develop**

| Service | Role | URL |
|---|---|---|
| **control-dashboard** | the console (start/stop stacks, RAM budget) | http://localhost:8080 |
| **JupyterLab** | notebook IDE (`develop` stack) | http://localhost:8888 |
| **MinIO** | S3-compatible object store (artifacts/datasets/models) | http://localhost:9001 |
| **Postgres** | metadata database | localhost:5432 |
| **Redis** | cache / message + frame bus | localhost:6379 |

**Phase 1 — telemetry** (`track` + `monitor` stacks — toggle them on in the console)

| Service | Role | URL |
|---|---|---|
| **MLflow** | experiment tracking + model registry | http://localhost:5000 |
| **Aim** | fast run-comparison UI | http://localhost:43800 |
| **Grafana** | dashboards: ML Training, Host & Containers, Data Prep, Serving | http://localhost:3000 |
| **Prometheus** | metrics store | http://localhost:9090 |
| **cAdvisor / node-exporter** | container + host metrics | :8082 / :9100 |
| **Pushgateway** | receives live training/data metrics | http://localhost:9091 |

Turn on `track` + `monitor`, then run `notebooks/01_training_telemetry.ipynb` — it
streams live loss/accuracy/lr to Grafana's *ML Training* dashboard, logs to MLflow +
Aim, and registers a model. The one-line helper is `notebooks/openml_telemetry.py`.

**Phase 2 — data & labeling** (`label` stack)

| Service | Role | URL |
|---|---|---|
| **Label Studio** | image/text annotation, Postgres-backed | http://localhost:8081 |
| **DVC** | dataset versioning with a MinIO remote | CLI in Jupyter |

Turn on `label` (login `admin@openml.local` / `openml-admin`), then run
`notebooks/02_labeling_and_dvc.ipynb` — it generates a sample image set into the
shared `workspace/`, labels config for Label Studio, and versions the dataset to
MinIO with DVC. Label Studio serves images from the **shared `workspace` volume**
(Local Storage), so no S3 presigned-URL setup is needed — see
[`docs/labeling.md`](docs/labeling.md) for the MinIO-storage alternative.

**Phase 3 — pipelines** (`pipeline` stack)

| Service | Role | URL |
|---|---|---|
| **ZenML** | pipeline orchestration + pluggable stack components | http://localhost:8237 |

Turn on `pipeline` (+ `track` for MLflow), then run `notebooks/03_pipeline.ipynb` —
it registers a ZenML **stack** (MinIO S3 artifact store + MLflow tracker/registry) and
runs `ingest → preprocess → train → evaluate → register`. Steps + lineage appear in the
ZenML dashboard, metrics + the model in MLflow, artifacts in MinIO. ZenML makes trackers
and deployers swappable — see [`docs/pipelines.md`](docs/pipelines.md).

**Phase 4 — CI/CD** (`cicd` stack)

| Service | Role | URL |
|---|---|---|
| **Gitea** | local git + Actions (train-on-push) | http://localhost:3001 |
| **act-runner** | runs Actions jobs on the openml network | — |

Turn on `cicd` (login `openml` / `openml-admin`). Push `cicd/demo-repo/` to a Gitea
repo and its `.gitea/workflows/train.yml` trains and **registers `ci-model` to MLflow**
automatically. See [`docs/cicd.md`](docs/cicd.md).

## Common commands

```bash
make up        # start core (+ build images)
make develop   # start JupyterLab
make ps        # status of everything
make logs S=jupyter   # tail one service
make stop      # stop all containers (keeps data, frees RAM)
make down      # remove containers (keeps volumes)
make nuke      # remove containers AND volumes (wipes data)
make config    # validate the compose file
```

## Apple Silicon — two things to know

Docker Desktop on macOS runs Linux in a VM. That imposes two hard limits this
platform is designed around (details in
[`docs/macos-constraints.md`](docs/macos-constraints.md)):

1. **No camera/USB passthrough into containers** → the camera is bridged from
   the host (Phase 6).
2. **No Apple GPU (MPS/Metal) inside containers** → GPU-heavy training runs
   *natively on the host* against the same MinIO/MLflow endpoints; containers
   handle orchestration, tracking, serving, and CPU work.

Because you can't run every stack at once in 24 GB, the console shows a live
**memory-budget bar** and lets you switch stacks on/off. Recommended: give the
Docker Desktop VM ~12–14 GB (Settings → Resources).

## Configuration

Copy and edit environment/ports/credentials:

```bash
cp .env.example .env
```

Everything (ports, credentials, bucket names) lives in `.env`. See
[`docs/memory-and-profiles.md`](docs/memory-and-profiles.md) for the stack →
profile → RAM map.

## Security

Designed for a single personal machine:

- **Host ports bind to `127.0.0.1`** by default (`BIND_HOST` in `.env`), so
  services are reachable only from this Mac. Set `BIND_HOST=0.0.0.0` to expose
  on your LAN — but only after adding auth and changing the default credentials.
- The **console mounts the Docker socket** (`/var/run/docker.sock`) read/write,
  which is effectively root on the host. That's inherent to a container that
  starts/stops other containers. Keep the dashboard port on `127.0.0.1` and
  don't expose it. The console refuses to stop/restart *itself*.
- Default credentials (`.env`) are for localhost only — change them for
  anything beyond your machine.
