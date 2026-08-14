# Serving (Phase 5)

The `serve` stack turns a model from the MLflow registry into a real-time
endpoint — SageMaker/Vertex "Endpoints" — plus a Gradio playground to test it.

| Service | Role | URL |
|---|---|---|
| `inference` | **BentoML** server, loads `models:/serve-demo@champion` | http://localhost:8000 |
| `playground` | **Gradio** "test your endpoint" UI | http://localhost:7860 |

## Quick start

The endpoint needs a model registered with the alias `champion`. The demo model
(`serve-demo`, sklearn iris) is registered like this:

```python
import mlflow
from mlflow import MlflowClient
from sklearn.datasets import load_iris
from sklearn.ensemble import RandomForestClassifier
mlflow.set_tracking_uri("http://mlflow:5000"); mlflow.set_experiment("serve-demo")
X, y = load_iris(return_X_y=True)
with mlflow.start_run():
    clf = RandomForestClassifier().fit(X, y)
    mlflow.sklearn.log_model(clf, "model", registered_model_name="serve-demo")
v = MlflowClient().search_model_versions("name='serve-demo'")[0].version
MlflowClient().set_registered_model_alias("serve-demo", "champion", v)
```

Then turn on **Serve** in the console (needs `track` for MLflow). Call it:

```bash
curl -s localhost:8000/predict -H 'Content-Type: application/json' \
  -d '{"inputs": [[5.1, 3.5, 1.4, 0.2]]}'
# -> {"predictions":[0],"labels":["setosa"]}
```

Open the **Playground** (:7860), enter the 4 iris measurements, get a prediction.

## Design (pluggable, per the architecture decision)

- **BentoML is the default runtime** (`serving/bentoml/`) — batching, OpenAPI,
  Prometheus `/metrics` on the same port, one-command containerization. Prometheus
  scrapes it as the `inference` job → the Grafana **Serving** dashboard.
- **A raw FastAPI example** ships in `serving/fastapi/` for the transparent
  "see the whole path" version (loads the same model, exposes `/predict`,
  `/healthz`, `/metrics` with `openml_inference_*` counters). To run it instead,
  point the `inference` service's `build.context` at `./serving/fastapi`.
- **Cluster path:** MLServer (V2 protocol) → KServe/Seldon is the scale-out
  route; because we standardize on MLflow models, moving there is config, not a
  rewrite. Swappable as a ZenML **model-deployer** component.

## Retrain → redeploy (closes the CI loop)

Register a new model version + move the `champion` alias, then restart the
`inference` service (or wire it into the Phase-4 `train-on-push` workflow) to
serve the new model.
