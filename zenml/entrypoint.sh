#!/bin/sh
set -e
# The ZenML server app runs DB migrations but does NOT seed the default
# user/workspace — the client store-init does. Without a default user, the
# NO_AUTH scheme can't resolve DEFAULT_USERNAME and every request 500s.
# Touch the local store once (idempotent) so the default user exists, then serve.
zenml user list >/dev/null 2>&1 || true
exec uvicorn zenml.zen_server.zen_server_api:app \
  --proxy-headers --forwarded-allow-ips '*' --host 0.0.0.0 --port 8080
