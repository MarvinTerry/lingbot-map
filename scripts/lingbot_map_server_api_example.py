#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import uuid
from pathlib import Path
from urllib import error, parse, request


def auth_headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def json_request(method: str, url: str, *, headers: dict[str, str] | None = None, data: bytes | None = None) -> dict:
    req = request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with request.urlopen(req) as resp:
            return json.load(resp)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: {exc.code} {body}") from exc


def raw_request(method: str, url: str, *, headers: dict[str, str] | None = None, data: bytes | None = None) -> bytes:
    req = request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with request.urlopen(req) as resp:
            return resp.read()
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: {exc.code} {body}") from exc


def encode_multipart(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = f"----LingBotMapBoundary{uuid.uuid4().hex}"
    file_name = file_path.name
    content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    chunks: list[bytes] = []

    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )

    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), boundary


def create_job(args: argparse.Namespace) -> dict:
    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    fields = {
        "fps": str(args.fps),
        "mode": args.mode,
        "window_size": str(args.window_size),
        "overlap_size": str(args.overlap_size),
        "num_scale_frames": str(args.num_scale_frames),
        "mask_sky": "true" if args.mask_sky else "false",
    }
    if args.keyframe_interval is not None:
        fields["keyframe_interval"] = str(args.keyframe_interval)

    body, boundary = encode_multipart(fields, "file", video_path)
    headers = {
        **auth_headers(args.api_key),
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    return json_request("POST", f"{args.base_url}/jobs", headers=headers, data=body)


def wait_for_job(args: argparse.Namespace, job_id: str) -> dict:
    deadline = time.time() + args.timeout
    while True:
        job = json_request(
            "GET",
            f"{args.base_url}/jobs/{job_id}",
            headers=auth_headers(args.api_key),
        )
        status = job.get("status")
        progress = job.get("progress", {})
        print(
            f"[poll] status={status} "
            f"phase={progress.get('phase')} "
            f"overall={progress.get('overall_percent')}"
        )
        if status in {"succeeded", "failed"}:
            return job
        if time.time() >= deadline:
            raise TimeoutError(f"Job {job_id} did not finish within {args.timeout} seconds")
        time.sleep(args.poll_interval)


def download_artifacts(args: argparse.Namespace, job: dict) -> None:
    download_dir = Path(args.download_dir).expanduser().resolve()
    download_dir.mkdir(parents=True, exist_ok=True)

    for artifact in job.get("artifacts", []):
        target = download_dir / artifact["filename"]
        print(f"[download] {artifact['name']} -> {target}")
        data = raw_request(
            "GET",
            parse.urljoin(args.base_url, artifact["url"]),
            headers=auth_headers(args.api_key),
        )
        target.write_bytes(data)


def delete_job(args: argparse.Namespace, job_id: str) -> None:
    req = request.Request(
        f"{args.base_url}/jobs/{job_id}",
        headers=auth_headers(args.api_key),
        method="DELETE",
    )
    try:
        with request.urlopen(req):
            pass
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DELETE job failed: {exc.code} {body}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LingBot-Map Server API example")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--mode", choices=["streaming", "windowed"], default="streaming")
    parser.add_argument("--window-size", type=int, default=64)
    parser.add_argument("--overlap-size", type=int, default=16)
    parser.add_argument("--keyframe-interval", type=int, default=None)
    parser.add_argument("--num-scale-frames", type=int, default=8)
    parser.add_argument("--mask-sky", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--download-dir", default="./tmp/lingbot-map-api-downloads")
    parser.add_argument("--delete-after", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.base_url = args.base_url.rstrip("/")

    healthz = json_request("GET", f"{args.base_url}/healthz")
    print("[healthz]", json.dumps(healthz, ensure_ascii=False))

    created = create_job(args)
    job_id = created["job_id"]
    print("[created]", json.dumps({"job_id": job_id, "status": created.get("status")}, ensure_ascii=False))

    job = wait_for_job(args, job_id)
    print("[finished]", json.dumps({"job_id": job_id, "status": job.get("status")}, ensure_ascii=False))

    if job.get("status") != "succeeded":
        print(json.dumps(job, ensure_ascii=False, indent=2))
        return 1

    download_artifacts(args, job)

    if args.delete_after:
        delete_job(args, job_id)
        print(f"[deleted] {job_id}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
