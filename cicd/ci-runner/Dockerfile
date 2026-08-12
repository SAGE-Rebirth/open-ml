# Job image for Gitea Actions "train-on-push". Needs node (for JS actions like
# actions/checkout) plus a Python ML client to train and register to MLflow.
# Kept lean on purpose — CI does not need the full Jupyter/ZenML environment.
FROM node:20-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      git python3 python3-pip ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --break-system-packages \
      mlflow==2.19.0 scikit-learn==1.5.2 boto3 s3fs

# node + python on PATH; used by the runner as the job container
