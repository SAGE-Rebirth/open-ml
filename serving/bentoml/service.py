"""BentoML serving service for the OpenML `serve-demo` iris model.

Loads the champion model from the MLflow registry once at startup and
exposes a single POST /predict endpoint. MLflow/MinIO endpoints and
credentials are injected by docker-compose at runtime (never hardcoded).
"""

import bentoml
import mlflow
import numpy as np

LABELS = ["setosa", "versicolor", "virginica"]


@bentoml.service
class ServeDemo:
    def __init__(self) -> None:
        self.model = mlflow.pyfunc.load_model("models:/serve-demo@champion")

    @bentoml.api
    def predict(self, inputs: list[list[float]]) -> dict:
        preds = self.model.predict(np.array(inputs)).astype(int).tolist()
        return {
            "predictions": preds,
            "labels": [LABELS[p] for p in preds],
        }
