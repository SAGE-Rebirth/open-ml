# CI/CD (Phase 4) — Gitea + Actions

The `cicd` stack runs a local **Gitea** (git server + Actions) and a
**Gitea Actions runner**, so a `git push` can train and register a model —
the SageMaker Projects / Vertex CI equivalent, fully local.

## Pieces

| Service | Role |
|---|---|
| `gitea` | git server + Actions, Postgres-backed (`gitea` db), HTTP on :3001 |
| `gitea-init` | one-shot: creates the admin + writes a runner registration token |
| `act-runner` | registers with Gitea, runs job containers on the `openml` network |
| `openml/ci-runner` | lean job image (node + python + mlflow + sklearn) |

Login (from `.env`): `openml` / `openml-admin`.

## The non-obvious bits (that took real debugging)

- **`generate-runner-token` needs the running server.** It calls Gitea's
  *internal* API, which only exists inside the live gitea container — a
  standalone `gitea` CLI returns "Internal Server Connection Error". So
  `gitea-init` uses `docker exec` into the running container.
- **act_runner registers via env vars, not flags.** The official image's
  entrypoint reads `GITEA_INSTANCE_URL` + `GITEA_RUNNER_REGISTRATION_TOKEN(_FILE)`
  — passing `--instance`/`--token` to a custom entrypoint fails with
  "instance address is empty". We let the default entrypoint do it and only
  provide the env + a mounted config. Registration persists in `/data/.runner`,
  so restarts don't re-register.
- **Job containers must join `openml_net`** (set in `cicd/runner-config.yaml`)
  so `mlflow`/`minio` resolve by name. `force_pull: false` keeps it from trying
  to pull the local-only `ci-runner` image.

## train-on-push

`cicd/demo-repo/` holds the example: `train.py` + `.gitea/workflows/train.yml`.
Push it and the runner trains + registers `ci-model` to MLflow:

```bash
# create the repo, then:
git remote add origin http://openml:openml-admin@localhost:3001/openml/demo.git
git push -u origin main
```

The workflow (`runs-on: openml`) checks out the code and runs `train.py`, which
logs to MLflow and registers the model. Verified end-to-end: push → Gitea run
`success` → `ci-model` in the MLflow registry.

> Extend the workflow with a deploy step in Phase 5 (redeploy the BentoML
> endpoint from the new registry version).
