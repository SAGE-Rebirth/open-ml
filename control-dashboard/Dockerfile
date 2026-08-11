# Docker CLI + compose/buildx plugins (multi-arch: works on Apple Silicon)
FROM docker:27-cli AS cli

FROM python:3.12-slim
# bring in the docker CLI and its compose/buildx plugins
COPY --from=cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=cli /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
