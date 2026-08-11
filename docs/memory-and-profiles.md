# Memory & profiles

On a 24 GB M4 you cannot run everything at once. Group services into stacks,
run only what you need, and watch the console's budget bar.

## Approximate idle footprint

| Stack (profile) | Services | ~Idle RAM |
|---|---|---|
| `core` *(always on)* | control-dashboard, postgres, minio, redis | ~0.5 GB |
| `develop` | jupyter | ~0.4 GB |
| `track` | mlflow, aim | ~0.45 GB |
| `monitor` | prometheus, grafana, cadvisor, node-exporter, pushgateway | ~0.9 GB |
| `label` | label-studio | ~0.6 GB |
| `pipeline` | zenml | ~0.4 GB |
| `cicd` | gitea, act-runner | ~0.35 GB |
| `serve` | inference | ~0.2 GB + model |
| `vision` | frame-consumer | ~0.05 GB (bridge is host-native) |

A comfortable everyday set is `core + develop + track + monitor` ≈ **2.3 GB
idle**, leaving the rest of the VM for actual CPU training.

## Suggested Docker Desktop settings

- **Memory:** 12–14 GB
- **CPUs:** 6–8
- **Swap:** 1–2 GB
- **Disk:** ≥ 60 GB (images + MinIO data grow over time)

## Recipes

- **Just exploring data** → `core + develop`
- **Training with live telemetry** → `core + develop + track + monitor`, then
  run the heavy training natively on the host (see `macos-constraints.md`)
- **Labeling session** → `core + label` (stop `monitor`/`track` to free RAM)
- **Serving a model** → `core + serve` (+ `monitor` for endpoint metrics)

Toggle stacks off in the console when you're done — `stop` keeps the container
(instant restart) while returning its memory to the VM.
