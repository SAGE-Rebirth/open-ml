# OpenML — architecture

OpenML reproduces the useful parts of AWS SageMaker AI / Google Vertex AI on a
single Apple Silicon machine using Docker Compose, plus a custom console.

## Concept mapping

| SageMaker / Vertex | OpenML component | Stack (profile) |
|---|---|---|
| Studio / Workbench notebooks | JupyterLab | `develop` |
| Ground Truth / Data Labeling | Label Studio | `label` |
| Feature/data versioning | DVC (MinIO remote) | in `develop` |
| Pipelines | ZenML | `pipeline` |
| Experiments / tracking | MLflow + Aim | `track` |
| Model Monitor / infra metrics | Prometheus + Grafana + cAdvisor + node-exporter + pushgateway + postgres/redis/blackbox exporters | `monitor` |
| Projects / CI-CD | Gitea + Actions | `cicd` |
| Endpoints (real-time inference) | BentoML (+ Gradio playground) | `serve` |
| Artifact store (S3) | MinIO | `core` |
| Metadata DB | Postgres | `core` |
| Message/frame bus | Redis | `core` |
| The AWS/GCP Console | **custom control-dashboard** | `core` |

## Stacks & profiles

Services are grouped by Compose **profiles**. `core` services have no profile
(always start). Everything else is started on demand — the console names the
services explicitly (`docker compose up -d <svc>`), which activates the profile,
and stops them with `docker compose stop <svc>` (keeps the container for a fast
restart while freeing its RAM).

```
core     : control-dashboard, postgres, minio, redis      (always on)
develop  : jupyter
track    : mlflow, aim                                     (Phase 1)
monitor  : prometheus, grafana, cadvisor, node-exporter, pushgateway,
           postgres-exporter, redis-exporter, blackbox-exporter    (Phase 1)
label    : label-studio                                    (Phase 2)
pipeline : zenml                                           (Phase 3)
cicd     : gitea, act-runner                               (Phase 4)
serve    : inference (BentoML) + playground (Gradio)       (Phase 5)
vision   : frame-consumer (+ host-native camera bridge)   (Phase 6)
```

## How the console controls stacks

The `control-dashboard` container mounts:

- the **docker socket** (`/var/run/docker.sock`) — to talk to the daemon, and
- the **project directory at the same absolute path** as on the host
  (`$OPENML_PROJECT_DIR:$OPENML_PROJECT_DIR`) — so that `docker compose` run
  *inside* the container resolves `./notebooks`-style bind mounts and build
  contexts to host-valid paths.

It lists containers by the label `openml.managed=true`, groups them by
`openml.stack`, reads live CPU/RAM via `docker stats`, and drives lifecycle with
`docker compose`. See `control-dashboard/app/`.

## Networking & storage

- Single user-defined bridge network `openml_net`; services address each other
  by name (`minio:9000`, `postgres:5432`, `redis:6379`).
- MinIO is the S3 backbone — MLflow artifacts, datasets, models, and the DVC
  remote all live there (mirrors how SageMaker/Vertex lean on S3/GCS).
- Named volumes persist `pgdata` and `miniodata`; `./notebooks` and
  `./workspace` are bind-mounted for live host editing.

## Build order (phases)

Each phase ends in something runnable and is verified before the next. See the
roadmap tiles in the console and the plan at
`~/.claude/plans/bright-cooking-seahorse.md`.
