# Pipelines (Phase 3) — ZenML

The `pipeline` stack runs a native-arm64 **ZenML server** that orchestrates ML
pipelines and makes the stack components (tracker, registry, artifact store,
deployer) swappable — this is what keeps OpenML generic.

## Architecture notes (why it's built this way)

- **Native arm64 image** — the official `zenmldocker/zenml-server` is amd64-only
  and would run under QEMU on Apple Silicon. We build `zenml/Dockerfile` from
  `python:3.12-slim + zenml[server]==0.96.3`, pinned to the **same version** as
  the client in the Jupyter image (client/server must match).
- **SQLite store, single uvicorn worker** — one writer, no lock races; persisted
  in the `zenml` volume. Fine for a single-user personal server (no MySQL needed).
- **`NO_AUTH` + default-user seed** — the server is localhost-only, so it runs
  with `ZENML_SERVER_AUTH_SCHEME=NO_AUTH`; the Jupyter client connects with just
  `ZENML_STORE_URL=http://zenml:8080`. The server app doesn't seed the default
  user on its own, so `zenml/entrypoint.sh` runs one CLI touch before starting
  uvicorn (otherwise NO_AUTH 500s on a fresh DB).

## The stack

`notebooks/03_pipeline.ipynb` registers (idempotently) and activates:

| Component | Flavor | Config |
|---|---|---|
| artifact store | `s3` | `s3://datasets/zenml`, `endpoint_url=http://minio:9000` |
| experiment tracker | `mlflow` | `tracking_uri=http://mlflow:5000` (+ dummy creds — see below) |
| model registry | `mlflow` | uses the MLflow server |
| orchestrator | `local` | runs steps in-process |

**Two gotchas the notebook handles for you:**

1. **`zenml init` first** — from a notebook (no `__file__`) ZenML can't resolve a
   custom flavor's source root; `zenml init` marks the folder as the root.
2. **Dummy MLflow creds** — ZenML's MLflow tracker *requires* auth for a remote
   tracking URI; our MLflow has none, so we pass throwaway
   `--tracking_username/--tracking_password` that MLflow ignores.

## Pluggability

Swap a component and re-run — no pipeline code changes:

```bash
# e.g. use Weights & Biases instead of MLflow for tracking
zenml experiment-tracker register wandb --flavor wandb   # needs WANDB_API_KEY
zenml stack update openml -e wandb
```

The same applies to model **deployers** (BentoML / Seldon / KServe) in Phase 5.
