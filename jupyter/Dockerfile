# JupyterLab for OpenML — arm64-native (Apple Silicon) scientific Python stack.
# Base provides numpy/pandas/sklearn/matplotlib/jupyterlab out of the box.
FROM quay.io/jupyter/scipy-notebook:2024-12-23

LABEL org.opencontainers.image.title="OpenML JupyterLab"

# system libs OpenCV needs at runtime (headless still wants libgl/glib)
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
USER ${NB_UID}

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && fix-permissions "${CONDA_DIR}" \
    && fix-permissions "/home/${NB_USER}"

# default working area (bind-mounted from the host in docker-compose.yml)
WORKDIR /home/${NB_USER}/work
