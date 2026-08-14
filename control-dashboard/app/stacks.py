"""
Stack registry — the single source of truth the dashboard uses to group
containers, know how to start/stop them, and build clickable UI links.

Keep the `services` names in sync with docker-compose.yml service names.
Stacks with available=False are on the roadmap (later phases); the UI shows
them greyed out so the whole platform vision is visible from day one.
"""
import os


def _port(name: str, default: str) -> str:
    return os.environ.get(name, default)


# host used in links shown to the user's browser
HOST = os.environ.get("OPENML_LINK_HOST", "localhost")


def link(port_env: str, default: str, path: str = "/") -> str:
    return f"http://{HOST}:{_port(port_env, default)}{path}"


STACKS = [
    {
        "key": "core",
        "title": "Core",
        "phase": 0,
        "available": True,
        "always_on": True,
        "description": "Storage, database, cache and this console. Always on.",
        "services": ["postgres", "minio", "redis", "control-dashboard"],
        "links": [
            {"label": "MinIO Console", "url": link("MINIO_CONSOLE_PORT", "9001")},
            {"label": "MinIO API", "url": link("MINIO_API_PORT", "9000")},
        ],
    },
    {
        "key": "develop",
        "title": "Develop · JupyterLab",
        "phase": 0,
        "available": True,
        "always_on": False,
        "description": "Notebook IDE with torch, sklearn, opencv, dvc, mlflow, zenml clients.",
        "services": ["jupyter"],
        "links": [
            {"label": "JupyterLab", "url": link("JUPYTER_PORT", "8888")},
        ],
    },
    # ---- roadmap (added in later phases) -----------------------------------
    {
        "key": "track", "title": "Track · MLflow + Aim", "phase": 1,
        "available": True, "always_on": False,
        "description": "Experiment tracking, run comparison and model registry.",
        "services": ["mlflow", "aim"],
        "links": [
            {"label": "MLflow", "url": link("MLFLOW_PORT", "5000")},
            {"label": "Aim", "url": link("AIM_PORT", "43800")},
        ],
    },
    {
        "key": "monitor", "title": "Monitor · Prometheus + Grafana", "phase": 1,
        "available": True, "always_on": False,
        "description": "Live metrics, gauges and dashboards for training, host and containers.",
        "services": ["prometheus", "grafana", "cadvisor", "node-exporter", "pushgateway",
                     "postgres-exporter", "redis-exporter", "blackbox-exporter"],
        "links": [
            {"label": "Grafana", "url": link("GRAFANA_PORT", "3000")},
            {"label": "Prometheus", "url": link("PROMETHEUS_PORT", "9090")},
            {"label": "cAdvisor", "url": link("CADVISOR_PORT", "8082")},
            {"label": "Pushgateway", "url": link("PUSHGATEWAY_PORT", "9091")},
        ],
    },
    {
        "key": "label", "title": "Label · Label Studio", "phase": 2,
        "available": True, "always_on": False,
        "description": "Data annotation backed by Postgres, serving images from your workspace.",
        "services": ["label-studio"],
        "links": [
            {"label": "Label Studio", "url": link("LABELSTUDIO_PORT", "8081")},
        ],
    },
    {
        "key": "pipeline", "title": "Pipelines · ZenML", "phase": 3,
        "available": True, "always_on": False,
        "description": "Orchestrate ingest → preprocess → train → evaluate → register (pluggable stack).",
        "services": ["zenml"],
        "links": [
            {"label": "ZenML", "url": link("ZENML_PORT", "8237")},
        ],
    },
    {
        "key": "cicd", "title": "CI/CD · Gitea Actions", "phase": 4,
        "available": True, "always_on": False,
        "description": "Local git + Actions runner: train-on-push → register model.",
        "services": ["gitea", "act-runner"],
        "links": [
            {"label": "Gitea", "url": link("GITEA_PORT", "3001")},
        ],
    },
    {
        "key": "serve", "title": "Serve · BentoML + Gradio", "phase": 5,
        "available": True, "always_on": False,
        "description": "Real-time inference endpoint (loads from the MLflow registry) + a Gradio playground.",
        "services": ["inference", "playground"],
        "links": [
            {"label": "Inference API", "url": link("INFERENCE_PORT", "8000")},
            {"label": "Playground", "url": link("PLAYGROUND_PORT", "7860")},
        ],
    },
    {
        "key": "vision", "title": "Vision · Camera bridge", "phase": 6,
        "available": False, "always_on": False,
        "description": "Host-native camera bridge (MJPEG/RTSP + Redis) with a container consumer.",
        "services": ["frame-consumer"], "links": [],
    },
]

# service name -> stack key  (only for available stacks / real services)
SERVICE_STACK = {
    svc: s["key"]
    for s in STACKS
    for svc in s["services"]
}

# services that belong to an always-on (core) stack — the API must refuse to
# `stop` these (mirrors the UI, which hides the stop control for core infra).
ALWAYS_ON_SERVICES = {
    svc for s in STACKS if s["always_on"] for svc in s["services"]
}

# compose service name -> concrete container_name in docker-compose.yml
CONTAINER_NAME = {
    "postgres": "openml-postgres",
    "minio": "openml-minio",
    "redis": "openml-redis",
    "control-dashboard": "openml-dashboard",
    "jupyter": "openml-jupyter",
    "mlflow": "openml-mlflow",
    "aim": "openml-aim",
    "prometheus": "openml-prometheus",
    "grafana": "openml-grafana",
    "cadvisor": "openml-cadvisor",
    "node-exporter": "openml-node-exporter",
    "pushgateway": "openml-pushgateway",
    "postgres-exporter": "openml-postgres-exporter",
    "redis-exporter": "openml-redis-exporter",
    "blackbox-exporter": "openml-blackbox-exporter",
    "label-studio": "openml-label-studio",
    "zenml": "openml-zenml",
    "gitea": "openml-gitea",
    "act-runner": "openml-act-runner",
    "inference": "openml-inference",
    "playground": "openml-playground",
}

# One-shot setup/init jobs. These run once and exit(0) on success (like k8s
# init-containers). The console shows them as a compact "Setup jobs" strip so
# their "Exited (0)" state reads as "completed", not "broken".
SETUP_JOBS = [
    {"service": "minio-init", "label": "MinIO buckets", "container": "openml-minio-init"},
    {"service": "db-init", "label": "Databases", "container": "openml-db-init"},
    {"service": "gitea-init", "label": "Gitea admin + runner token", "container": "openml-gitea-init"},
    {"service": "ci-runner", "label": "CI job image", "container": "openml-ci-runner"},
]
