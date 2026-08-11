# Native arm64 ZenML server (the official image is amd64-only → would run under
# QEMU emulation on Apple Silicon). Pinned to the SAME version as the client in
# the Jupyter image so REST client/server stay compatible.
FROM python:3.12-slim

RUN pip install --no-cache-dir "zenml[server]==0.96.3" && rm -rf /root/.cache

ENV ZENML_CONFIG_PATH=/zenml/.zenconfig \
    ZENML_CONTAINER=1 \
    ZENML_ANALYTICS_OPT_IN=false \
    ZENML_DEBUG=false

RUN mkdir -p /zenml/.zenconfig
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
WORKDIR /zenml
EXPOSE 8080

# entrypoint seeds the default user (see entrypoint.sh) then starts a single
# uvicorn worker → SQLite store has one writer (no lock races).
CMD ["/entrypoint.sh"]
