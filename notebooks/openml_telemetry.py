"""
openml_telemetry — one tiny helper so training code logs everywhere at once:

  * MLflow     — params, metrics, artifacts, model registry (the system of record)
  * Pushgateway — live gauges Prometheus scrapes → Grafana "ML Training" dashboard
  * Aim        — fast experiment-comparison UI

Everything is best-effort: if the track/monitor stacks are off, calls warn and
continue so your notebook still runs.

Usage
-----
    import openml_telemetry as tel

    with tel.TrainingRun("mnist-demo", params={"lr": 1e-3, "epochs": 20}) as run:
        for epoch in range(20):
            ...
            run.log(step=epoch, epoch=epoch, loss=loss, accuracy=acc, lr=lr)
        run.register_torch(model, "mnist-mlp")     # -> MLflow Model Registry
"""
from __future__ import annotations

import os
import warnings
from typing import Optional

_PUSHGW = os.environ.get("OPENML_PUSHGATEWAY_URL", "http://pushgateway:9091").replace("http://", "")
_AIM_REPO = os.environ.get("OPENML_AIM_REPO", "aim://aim:53800")


def _warn(msg: str) -> None:
    warnings.warn(f"[openml_telemetry] {msg}", stacklevel=2)


def push_dataset_stats(dataset: str, rows: int,
                       classes: Optional[dict] = None,
                       splits: Optional[dict] = None) -> None:
    """Push data-prep metrics for the Grafana 'Data Prep' dashboard."""
    try:
        from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
    except Exception as e:  # pragma: no cover
        return _warn(f"prometheus_client missing: {e}")
    reg = CollectorRegistry()
    Gauge("openml_dataset_rows", "rows in dataset", ["dataset"], registry=reg).labels(dataset).set(rows)
    if classes:
        g = Gauge("openml_class_count", "samples per class", ["dataset", "class"], registry=reg)
        for cls, n in classes.items():
            g.labels(dataset, str(cls)).set(n)
    if splits:
        g = Gauge("openml_split_size", "rows per split", ["dataset", "split"], registry=reg)
        for split, n in splits.items():
            g.labels(dataset, str(split)).set(n)
    try:
        push_to_gateway(_PUSHGW, job="dataprep", grouping_key={"dataset": dataset}, registry=reg)
    except Exception as e:
        _warn(f"pushgateway unreachable ({_PUSHGW}): {e}")


class TrainingRun:
    """Context manager fanning out params/metrics to MLflow, Pushgateway and Aim."""

    def __init__(self, experiment: str, run_name: Optional[str] = None,
                 params: Optional[dict] = None):
        self.experiment = experiment
        self.run_name = run_name or _default_run_name()
        self.params = params or {}
        self._mlflow = None
        self._aim = None

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> "TrainingRun":
        # MLflow
        try:
            import mlflow
            mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
            mlflow.set_experiment(self.experiment)
            self._active = mlflow.start_run(run_name=self.run_name)
            if self.params:
                mlflow.log_params(self.params)
            self._mlflow = mlflow
        except Exception as e:
            _warn(f"MLflow unavailable: {e}")
        # Aim
        try:
            import aim
            self._aim = aim.Run(repo=_AIM_REPO, experiment=self.experiment)
            self._aim["hparams"] = self.params
        except Exception as e:
            _warn(f"Aim unavailable: {e}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._mlflow is not None:
            try:
                self._mlflow.end_run(status="FAILED" if exc_type else "FINISHED")
            except Exception:
                pass
        if self._aim is not None:
            try:
                self._aim.close()
            except Exception:
                pass
        # Clear this run's LIVE gauges from Pushgateway so they don't linger as
        # a stale flat-line forever. The full history is already in Prometheus
        # (scraped every 5s during the run) and in MLflow/Aim.
        try:
            from prometheus_client import delete_from_gateway
            delete_from_gateway(_PUSHGW, job=self.experiment,
                                grouping_key={"run": self.run_name})
        except Exception:
            pass

    # -- logging -----------------------------------------------------------
    def log(self, step: int, epoch: Optional[int] = None, **metrics: float) -> None:
        """Log a step of metrics (loss, accuracy, lr, ...) to all backends."""
        # MLflow
        if self._mlflow is not None:
            try:
                self._mlflow.log_metrics({k: float(v) for k, v in metrics.items()}, step=step)
            except Exception as e:
                _warn(f"mlflow.log_metrics: {e}")
        # Aim
        if self._aim is not None:
            try:
                for k, v in metrics.items():
                    self._aim.track(float(v), name=k, step=step, context={"subset": "train"})
            except Exception as e:
                _warn(f"aim.track: {e}")
        # Pushgateway (live gauges)
        self._push(step, epoch, metrics)

    def _push(self, step: int, epoch: Optional[int], metrics: dict) -> None:
        try:
            from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
        except Exception:
            return
        reg = CollectorRegistry()
        for k, v in metrics.items():
            try:
                Gauge(f"openml_train_{k}", f"train {k}", registry=reg).set(float(v))
            except Exception:
                pass
        Gauge("openml_step", "training step", registry=reg).set(step)
        if epoch is not None:
            Gauge("openml_epoch", "training epoch", registry=reg).set(epoch)
        try:
            push_to_gateway(_PUSHGW, job=self.experiment,
                            grouping_key={"run": self.run_name}, registry=reg)
        except Exception as e:
            _warn(f"pushgateway unreachable ({_PUSHGW}): {e}")

    # -- model registry ----------------------------------------------------
    def register_torch(self, model, name: str, **kwargs):
        return self._register("pytorch", model, name, **kwargs)

    def register_sklearn(self, model, name: str, **kwargs):
        return self._register("sklearn", model, name, **kwargs)

    def _register(self, flavor: str, model, name: str, **kwargs):
        if self._mlflow is None:
            return _warn("cannot register model: MLflow unavailable")
        try:
            mod = getattr(self._mlflow, flavor)
            info = mod.log_model(model, artifact_path="model",
                                 registered_model_name=name, **kwargs)
            print(f"[openml_telemetry] registered '{name}' -> {info.model_uri}")
            return info
        except Exception as e:
            _warn(f"register model failed: {e}")


def _default_run_name() -> str:
    # avoid importing datetime.now() randomness concerns — use a short pid+counter
    import time
    return f"run-{int(time.time()) % 100000}"
