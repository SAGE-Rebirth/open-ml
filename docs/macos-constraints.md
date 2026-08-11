# Apple Silicon / macOS constraints

Docker Desktop on macOS runs containers inside a lightweight Linux VM. Two
consequences shape OpenML's design.

## 1. No USB / camera passthrough into containers

The macOS Docker VM has no access to host USB devices or the Mac camera.
`--device=/dev/video0` and `/dev/bus/usb/...` simply do not exist there, so
OpenCV inside a container cannot open the camera directly.

**OpenML's answer (Phase 6): a host-native camera bridge.** A tiny Python
process runs *on macOS* (native venv), captures the camera with OpenCV, and
republishes frames as:

- an **MJPEG/RTSP** stream (viewable in a browser, consumable by containers), and
- **JPEG frames pushed to Redis** for containerized consumers.

Containers subscribe over `openml_net`. This is decoupled, works today, and
later extends cleanly to a Linux worker node with real device passthrough.

## 2. No Apple GPU (MPS / Metal) inside containers

Containers cannot use the M4 GPU. Anything that needs Metal acceleration
(`torch.device("mps")`) must run **natively on the host**, not in a container.

**OpenML's answer:** containers own orchestration, tracking, storage, serving,
and CPU work. For GPU-heavy training, run a **host-side venv/conda** that points
at the same endpoints the containers use:

```bash
export MLFLOW_TRACKING_URI=http://localhost:5000       # Phase 1+
export MLFLOW_S3_ENDPOINT_URL=http://localhost:9000
export AWS_ACCESS_KEY_ID=minioadmin AWS_SECRET_ACCESS_KEY=minioadmin123
# then train natively with torch.device("mps") — logs/artifacts land in the platform
```

Inside containers, `torch` runs on CPU. The smoke-test notebook prints this
explicitly so there's no confusion.

## Memory

24 GB total minus the Docker VM (recommended 12–14 GB) minus host/native
training means you cannot run every stack simultaneously. The console's
**memory-budget bar** and per-stack on/off switches exist precisely for this.
