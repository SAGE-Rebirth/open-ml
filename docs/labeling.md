# Labeling & data versioning (Phase 2)

## Label Studio

Runs in the `label` stack, backed by the shared **Postgres** (`labelstudio`
database, created by `db-init`) with data in the `labelstudio` volume.

Login (from `.env`): `admin@openml.local` / `openml-admin`.

### Why Local Storage, not S3 by default

Label Studio shows images **in your browser**. If you point it at MinIO with S3
storage, it hands the browser **presigned URLs using the internal `minio:9000`
hostname** — which the browser (on your Mac) can't resolve, so images won't load.
This is a split-horizon DNS problem, not a bug.

OpenML avoids it by mounting the shared `./workspace` folder into Label Studio at
`/label-studio/files` and enabling local-files serving. Label Studio serves the
images itself over its own (browser-reachable) port. The same folder is mounted in
Jupyter, so a notebook writes images and Label Studio reads them immediately.

**Add a source in the UI:** Settings → Cloud Storage → Add Source Storage →
**Local files** → Absolute local path `/label-studio/files/labeling/images` → Sync.

### If you really want MinIO/S3 source storage

Two options:

1. Add `127.0.0.1  minio` to your Mac's `/etc/hosts`. Then set the storage's S3
   endpoint to `http://minio:9000`; presigned URLs resolve in both the container
   and the browser.
2. Put a reverse proxy in front of MinIO on a hostname reachable from both.

For a personal single-machine setup, Local Storage is simpler and recommended.

## DVC → MinIO

DVC is installed in the Jupyter image (`dvc[s3]`, with `pathspec` pinned — newer
pathspec breaks dvc 3.59). Version a dataset and push it to MinIO:

```bash
cd /home/jovyan/work/workspace
dvc init --no-scm -f
dvc remote add -d -f minio s3://datasets/dvc
dvc remote modify minio endpointurl http://minio:9000
dvc add labeling      # creates labeling.dvc (the tiny pointer)
dvc push              # content-addressed data -> MinIO
```

Credentials come from the container's `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.
`labeling.dvc` is what you'd commit to git; `dvc pull` restores the data anywhere.
See `notebooks/02_labeling_and_dvc.ipynb` for the full walkthrough.
