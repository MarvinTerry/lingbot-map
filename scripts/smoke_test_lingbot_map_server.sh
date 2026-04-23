#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

HOST="${LINGBOT_MAP_SERVER_HOST:-127.0.0.1}"
PORT="${LINGBOT_MAP_SERVER_PORT:-18080}"
BASE_URL="http://$HOST:$PORT"
API_KEY="${LINGBOT_MAP_SERVER_API_KEY:-smoke-test-key}"
MODEL_PATH="${LINGBOT_MAP_MODEL_PATH:-$REPO_ROOT/checkpoints/robbyant-lingbot-map/lingbot-map.pt}"
VIDEO_PATH="${LINGBOT_MAP_SERVER_SMOKE_VIDEO:-$REPO_ROOT/58aceb3121bdd696e377637a4e3b58b7.mp4}"
TMP_DIR="$(mktemp -d)"
SERVER_LOG="$TMP_DIR/server.log"
JOB_JSON="$TMP_DIR/job.json"
ARTIFACTS_JSON="$TMP_DIR/artifacts.json"
JOB_ID_FILE="$TMP_DIR/job_id.txt"
DOWNLOADED_METADATA="$TMP_DIR/downloaded_metadata.json"

cleanup() {
  if [[ -f "$JOB_ID_FILE" ]]; then
    JOB_ID="$(cat "$JOB_ID_FILE")"
    curl -s -X DELETE -H "X-API-Key: $API_KEY" "$BASE_URL/jobs/$JOB_ID" >/dev/null || true
  fi
  if [[ -n "${SERVER_PID:-}" ]]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
  echo "Missing virtualenv python at $REPO_ROOT/.venv/bin/python" >&2
  exit 1
fi

if [[ ! -f "$MODEL_PATH" ]]; then
  echo "Model checkpoint not found: $MODEL_PATH" >&2
  exit 1
fi

if [[ ! -f "$VIDEO_PATH" ]]; then
  echo "Smoke video not found: $VIDEO_PATH" >&2
  exit 1
fi

export LINGBOT_MAP_MODEL_PATH="$MODEL_PATH"
export LINGBOT_MAP_SERVER_API_KEY="$API_KEY"
export LINGBOT_MAP_SERVER_HOST="$HOST"
export LINGBOT_MAP_SERVER_PORT="$PORT"
export PATH="$REPO_ROOT/.venv/bin:$PATH"

echo "[1/6] Starting server"
"$REPO_ROOT/scripts/run_lingbot_map_server.sh" >"$SERVER_LOG" 2>&1 &
SERVER_PID="$!"

echo "[2/6] Waiting for healthz"
for _ in $(seq 1 30); do
  if curl -s "$BASE_URL/healthz" >/dev/null; then
    break
  fi
  sleep 1
done
curl -s "$BASE_URL/healthz" > /dev/null

UPLOAD_UI_CODE="$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/ui/upload")"
if [[ "$UPLOAD_UI_CODE" != "200" ]]; then
  echo "Expected /ui/upload to return 200, got $UPLOAD_UI_CODE" >&2
  exit 1
fi

UNAUTH_CODE="$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/jobs/not-found")"
if [[ "$UNAUTH_CODE" != "401" ]]; then
  echo "Expected 401 without API key, got $UNAUTH_CODE" >&2
  exit 1
fi

echo "[3/6] Uploading sample mp4"
curl -s -X POST "$BASE_URL/jobs" \
  -H "X-API-Key: $API_KEY" \
  -F "file=@$VIDEO_PATH" \
  -F "fps=2" \
  -F "mode=streaming" \
  > "$JOB_JSON"

JOB_ID="$("$REPO_ROOT/.venv/bin/python" - <<'PY' "$JOB_JSON"
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)
print(data["job_id"])
PY
)"
echo "$JOB_ID" > "$JOB_ID_FILE"
echo "Job ID: $JOB_ID"

JOB_UI_CODE="$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/ui/jobs/$JOB_ID")"
if [[ "$JOB_UI_CODE" != "200" ]]; then
  echo "Expected /ui/jobs/$JOB_ID to return 200, got $JOB_UI_CODE" >&2
  exit 1
fi

echo "[4/6] Polling job status"
"$REPO_ROOT/.venv/bin/python" - <<'PY' "$BASE_URL" "$API_KEY" "$JOB_ID" "$JOB_JSON"
import json
import sys
import time
import urllib.request

base_url, api_key, job_id, output_path = sys.argv[1:5]
url = f"{base_url}/jobs/{job_id}"
req = urllib.request.Request(url, headers={"X-API-Key": api_key})

for _ in range(180):
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    print(f"status={data['status']}")
    if data["status"] in {"succeeded", "failed"}:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if data["status"] != "succeeded":
            raise SystemExit("job failed")
        raise SystemExit(0)
    time.sleep(1)

raise SystemExit("timeout waiting for job")
PY

echo "[5/6] Verifying artifacts"
curl -s -H "X-API-Key: $API_KEY" "$BASE_URL/jobs/$JOB_ID/artifacts" > "$ARTIFACTS_JSON"
"$REPO_ROOT/.venv/bin/python" - <<'PY' "$JOB_JSON" "$ARTIFACTS_JSON" "$BASE_URL" "$API_KEY" "$DOWNLOADED_METADATA"
import json
import sys
import urllib.request
from pathlib import Path

job_path, artifacts_path, base_url, api_key, downloaded_metadata = sys.argv[1:6]

with open(job_path, "r", encoding="utf-8") as f:
    job = json.load(f)
with open(artifacts_path, "r", encoding="utf-8") as f:
    artifacts = json.load(f)["artifacts"]

artifact_names = {item["name"] for item in artifacts}
expected = {"metadata_json", "log_txt", "scene_glb"}
missing = expected - artifact_names
if missing:
    raise SystemExit(f"missing artifacts: {sorted(missing)}")

scene_path = Path(job["paths"]["scene_glb"])
log_path = Path(job["paths"]["log_txt"])
metadata_path = Path(job["paths"]["metadata_json"])
for path in (scene_path, log_path, metadata_path):
    if not path.exists():
        raise SystemExit(f"expected file missing: {path}")

metadata_artifact = next(item for item in artifacts if item["name"] == "metadata_json")
req = urllib.request.Request(
    f"{base_url}{metadata_artifact['url']}",
    headers={"X-API-Key": api_key},
)
with urllib.request.urlopen(req) as resp:
    body = resp.read()
Path(downloaded_metadata).write_bytes(body)
downloaded = json.loads(body)
if downloaded["job_id"] != job["job_id"]:
    raise SystemExit("downloaded metadata job_id mismatch")
PY

echo "[6/6] Deleting job"
DELETE_CODE="$(curl -s -o /dev/null -w '%{http_code}' -X DELETE -H "X-API-Key: $API_KEY" "$BASE_URL/jobs/$JOB_ID")"
if [[ "$DELETE_CODE" != "204" ]]; then
  echo "Expected delete to return 204, got $DELETE_CODE" >&2
  exit 1
fi

GET_AFTER_DELETE="$(curl -s -o /dev/null -w '%{http_code}' -H "X-API-Key: $API_KEY" "$BASE_URL/jobs/$JOB_ID")"
if [[ "$GET_AFTER_DELETE" != "404" ]]; then
  echo "Expected deleted job to return 404, got $GET_AFTER_DELETE" >&2
  exit 1
fi

echo "Smoke test passed."
