# LingBot-Map Server

Phase 1 server for asynchronous `mp4 -> scene.glb` batch processing.

## Scope

This server intentionally does only a small set of things:

- accept an `mp4` upload
- enqueue one batch job on a single GPU worker
- run LingBot-Map inference through the existing `demo.py` pipeline
- export `scene.glb`
- expose job status, artifact listing, artifact download, and job deletion

It does not include first-person flythrough video generation, streaming output, or multi-worker scheduling.

## Minimal Web UI

The server now also includes a minimal browser UI:

- `/ui/upload`
- `/ui/workspace`

The UI is intentionally small:

- upload `mp4`
- save API key in browser local storage
- auto-jump to the workspace
- show all jobs in a left sidebar
- poll job status
- show queue/running progress in real time
- preview `scene.glb` in a large central Three.js viewer
- download artifacts
- delete the job

This UI does not replace the existing JSON API. It is just a thin layer on top of it.

## Requirements

- Python environment managed by `uv`
- working LingBot-Map checkpoint
- GPU runtime already installed and verified
- optional local proxy if you expect first-run downloads such as `skyseg.onnx`

## Install

When downloads are involved, export your proxy first:

```bash
export http_proxy="http://127.0.0.1:7890"
export https_proxy="http://127.0.0.1:7890"
export all_proxy="socks5://127.0.0.1:7890"
```

Install the server and visualization dependencies into the existing `uv` virtualenv:

```bash
uv pip install --python .venv/bin/python -e ".[server,vis]"
```

Note:

- prefer `uv pip install ...` here
- avoid `uv sync` unless the CUDA stack is also fully declared in your lock/dependency setup

## Configuration

Required environment variables:

- `LINGBOT_MAP_MODEL_PATH`
- `LINGBOT_MAP_SERVER_API_KEY`

Optional environment variables:

- `LINGBOT_MAP_SERVER_HOST`
- `LINGBOT_MAP_SERVER_PORT`
- `LINGBOT_MAP_SERVER_JOBS_DIR`
- `LINGBOT_MAP_SERVER_USE_SDPA`
- `LINGBOT_MAP_SERVER_OFFLOAD_TO_CPU`

The server automatically loads a repo-root `.env` file if present.

Recommended setup:

```bash
cp .env.example .env
```

Example `.env`:

```dotenv
LINGBOT_MAP_MODEL_PATH=/home/ubuntu/lingbot-map/checkpoints/robbyant-lingbot-map/lingbot-map.pt
LINGBOT_MAP_SERVER_API_KEY=change-me
LINGBOT_MAP_SERVER_HOST=0.0.0.0
LINGBOT_MAP_SERVER_PORT=8000
LINGBOT_MAP_SERVER_JOBS_DIR=/home/ubuntu/lingbot-map/outputs/jobs
LINGBOT_MAP_SERVER_OFFLOAD_TO_CPU=true
```

If you expect first-run downloads, you can also place proxy settings in `.env`:

```dotenv
http_proxy=http://127.0.0.1:7890
https_proxy=http://127.0.0.1:7890
all_proxy=socks5://127.0.0.1:7890
```

## Start

Use the provided helper script:

```bash
./scripts/run_lingbot_map_server.sh
```

Or launch manually:

```bash
PATH=/home/ubuntu/lingbot-map/.venv/bin:$PATH \
.venv/bin/python -m lingbot_map_server
```

Then open:

```text
http://127.0.0.1:8000/ui/workspace
```

## API

Public:

- `GET /healthz`

Authenticated:

- `GET /jobs`
- `POST /jobs`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/artifacts`
- `GET /artifacts/{artifact_id}`
- `DELETE /jobs/{job_id}`

Auth headers:

- `X-API-Key: <key>`
- `Authorization: Bearer <key>`

联调文档与参考代码：

- [`doc/lingbot-map-server-api.md`](../doc/lingbot-map-server-api.md)
- [`scripts/lingbot_map_server_api_example.py`](../scripts/lingbot_map_server_api_example.py)

## Quick Example

```bash
curl -X POST "http://127.0.0.1:8000/jobs" \
  -H "X-API-Key: change-me" \
  -F "file=@58aceb3121bdd696e377637a4e3b58b7.mp4" \
  -F "fps=2" \
  -F "mode=streaming"
```

## UI Notes

- The browser UI stores the API key in local storage.
- Artifact downloads and GLB preview still go through the authenticated artifact endpoints.
- The workspace uses a Three.js-based GLB viewer so the page can evolve toward richer camera/path-based 3D playback later.
- Server process configuration is loaded from environment variables and optional `.env`.

## Artifacts

Each successful job produces:

- `scene.glb`
- `metadata.json`
- `log.txt`

Stored under:

```text
outputs/jobs/{job_id}/
```

## Smoke Test

Run the included smoke test:

```bash
./scripts/smoke_test_lingbot_map_server.sh
```

By default it uses:

- model: `checkpoints/robbyant-lingbot-map/lingbot-map.pt`
- sample video: `58aceb3121bdd696e377637a4e3b58b7.mp4`
- host: `127.0.0.1`
- port: `18080`

The smoke test will:

1. start the server in the background
2. verify health check and auth rejection
3. upload the sample `mp4`
4. poll until the job finishes
5. verify artifacts
6. delete the job and verify cleanup
