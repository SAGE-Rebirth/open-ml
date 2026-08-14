"""Transparent FastAPI inference server for OpenML.

The lightweight "see the raw path" alternative to BentoML: load an MLflow
pyfunc model once at startup and serve predictions over plain HTTP.

Endpoints/credentials (MLFLOW_TRACKING_URI, MLFLOW_S3_ENDPOINT_URL,
AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY) are injected at runtime by
docker-compose; nothing is hardcoded here.
"""

from contextlib import asynccontextmanager
from time import perf_counter
from typing import List

import mlflow
import numpy as np
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel

MODEL_URI = "models:/serve-demo@champion"
LABELS = ["setosa", "versicolor", "virginica"]

REQUESTS = Counter(
    "openml_inference_requests_total",
    "Total inference requests handled.",
    ["path"],
)
LATENCY = Histogram(
    "openml_inference_latency_seconds",
    "Inference request latency in seconds.",
)

# Populated at startup, shared across requests.
model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the model once when the process starts."""
    global model
    model = mlflow.pyfunc.load_model(MODEL_URI)
    yield


app = FastAPI(title="OpenML FastAPI inference", lifespan=lifespan)


class PredictRequest(BaseModel):
    inputs: List[List[float]]


class PredictResponse(BaseModel):
    predictions: List[int]
    labels: List[str]


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest) -> PredictResponse:
    start = perf_counter()
    try:
        preds = model.predict(np.array(request.inputs)).astype(int).tolist()
        return PredictResponse(
            predictions=preds,
            labels=[LABELS[p] for p in preds],
        )
    finally:
        REQUESTS.labels(path="/predict").inc()
        LATENCY.observe(perf_counter() - start)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
