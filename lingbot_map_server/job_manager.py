from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import queue
import shutil
import signal
import subprocess
import threading
import uuid

import cv2

from lingbot_map_server.config import ServerSettings


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dump(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


class JobManager:
    def __init__(self, settings: ServerSettings):
        self.settings = settings
        self.settings.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, dict] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._processes: dict[str, subprocess.Popen] = {}
        self._load_jobs_from_disk()

    def start(self) -> None:
        if self._worker is not None:
            return
        self._worker = threading.Thread(target=self._worker_loop, name="lingbot-map-worker", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put("__shutdown__")
        process_items = []
        with self._lock:
            process_items = list(self._processes.items())
        for job_id, process in process_items:
            self._terminate_process(job_id, process)
        if self._worker is not None:
            self._worker.join(timeout=5)

    def reserve_job(
        self,
        filename: str,
        content_type: str | None,
        request_params: dict,
    ) -> dict:
        job_id = uuid.uuid4().hex
        job_dir = self.settings.jobs_dir / job_id
        input_dir = job_dir / "input"
        artifacts_dir = job_dir / "artifacts"
        logs_dir = job_dir / "logs"
        frames_dir = job_dir / "frames"
        for path in (input_dir, artifacts_dir, logs_dir, frames_dir):
            path.mkdir(parents=True, exist_ok=True)

        record = {
            "job_id": job_id,
            "status": "uploading",
            "created_at": _utcnow(),
            "queued_at": None,
            "started_at": None,
            "finished_at": None,
            "last_updated_at": _utcnow(),
            "error": None,
            "input": {
                "original_filename": filename,
                "content_type": content_type,
                "size_bytes": None,
                "sha256": None,
                "video": None,
            },
            "request": request_params,
            "runtime": {
                "model_path": str(self.settings.model_path),
                "python_executable": self.settings.python_executable,
                "workdir": str(self.settings.repo_root),
                "use_sdpa": self.settings.use_sdpa,
                "offload_to_cpu": self.settings.offload_to_cpu,
                "command": None,
                "pid": None,
                "return_code": None,
            },
            "progress": {
                "phase": "uploading",
                "label": "Uploading video",
                "overall_percent": 0.0,
                "phase_percent": 0.0,
                "current": 0,
                "total": None,
                "queue_position": None,
            },
            "paths": {
                "job_dir": str(job_dir),
                "input_video": str(input_dir / "input.mp4"),
                "artifacts_dir": str(artifacts_dir),
                "scene_glb": str(artifacts_dir / "scene.glb"),
                "log_txt": str(artifacts_dir / "log.txt"),
                "metadata_json": str(job_dir / "metadata.json"),
                "progress_json": str(job_dir / "progress.json"),
                "sky_mask_dir": str(job_dir / "sky_masks"),
                "sky_mask_visualization_dir": str(job_dir / "sky_mask_visualizations"),
                "frames_dir": str(frames_dir),
            },
        }
        with self._lock:
            self._jobs[job_id] = record
            self._persist_locked(record)
        return self.get_job(job_id)

    def complete_upload(
        self,
        job_id: str,
        size_bytes: int,
        sha256: str,
    ) -> dict:
        with self._lock:
            record = self._get_locked(job_id)
            input_video = Path(record["paths"]["input_video"])
            record["input"]["size_bytes"] = size_bytes
            record["input"]["sha256"] = sha256
            record["input"]["video"] = self._read_video_info(input_video)
            record["status"] = "queued"
            record["queued_at"] = _utcnow()
            record["last_updated_at"] = _utcnow()
            record["progress"] = {
                "phase": "queued",
                "label": "Waiting for GPU worker",
                "overall_percent": 0.0,
                "phase_percent": 0.0,
                "current": 0,
                "total": None,
                "queue_position": self._compute_queue_position_locked(job_id),
            }
            self._persist_locked(record)
        self._queue.put(job_id)
        return self.get_job(job_id)

    def fail_upload(self, job_id: str, error_message: str) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record["status"] = "failed"
            record["error"] = error_message
            record["finished_at"] = _utcnow()
            record["last_updated_at"] = _utcnow()
            record["progress"] = {
                "phase": "failed",
                "label": error_message,
                "overall_percent": record.get("progress", {}).get("overall_percent", 0.0),
                "phase_percent": 0.0,
                "current": 0,
                "total": None,
                "queue_position": None,
            }
            self._persist_locked(record)

    def get_job(self, job_id: str) -> dict:
        with self._lock:
            record = self._get_locked(job_id)
            return self._public_job(record)

    def list_artifacts(self, job_id: str) -> list[dict]:
        with self._lock:
            record = self._get_locked(job_id)
            return self._build_artifacts(record)

    def resolve_artifact(self, artifact_id: str) -> tuple[Path, str]:
        job_id, artifact_name = artifact_id.split(":", 1)
        with self._lock:
            record = self._get_locked(job_id)
            for artifact in self._build_artifacts(record):
                if artifact["artifact_id"] == artifact_id:
                    return Path(artifact["path"]), artifact["content_type"]
        raise KeyError(f"Artifact not found: {artifact_id}")

    def delete_job(self, job_id: str) -> None:
        with self._lock:
            record = self._get_locked(job_id)
            record["status"] = "deleting"
            record["last_updated_at"] = _utcnow()
            self._persist_locked(record)
            process = self._processes.get(job_id)
            job_dir = Path(record["paths"]["job_dir"])

        if process is not None:
            self._terminate_process(job_id, process)

        shutil.rmtree(job_dir, ignore_errors=True)
        with self._lock:
            self._processes.pop(job_id, None)
            self._jobs.pop(job_id, None)

    def _load_jobs_from_disk(self) -> None:
        for metadata_path in sorted(self.settings.jobs_dir.glob("*/metadata.json")):
            with metadata_path.open("r", encoding="utf-8") as f:
                record = json.load(f)
            if record["status"] == "queued":
                self._jobs[record["job_id"]] = record
                self._queue.put(record["job_id"])
                continue
            if record["status"] in {"running", "uploading", "deleting"}:
                record["status"] = "failed"
                record["error"] = "Server restarted before the job completed."
                record["finished_at"] = _utcnow()
                record["last_updated_at"] = _utcnow()
                _json_dump(record, metadata_path)
            self._jobs[record["job_id"]] = record

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if job_id == "__shutdown__":
                return

            with self._lock:
                record = self._jobs.get(job_id)
                if record is None or record["status"] != "queued":
                    continue
                record["status"] = "running"
                record["started_at"] = _utcnow()
                record["last_updated_at"] = _utcnow()
                record["progress"] = {
                    "phase": "starting",
                    "label": "Starting inference process",
                    "overall_percent": 1.0,
                    "phase_percent": 0.0,
                    "current": 0,
                    "total": None,
                    "queue_position": None,
                }
                command = self._build_command(record)
                record["runtime"]["command"] = command
                self._persist_locked(record)
                log_path = Path(record["paths"]["log_txt"])

            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(f"[{_utcnow()}] Starting job {job_id}\n")
                log_file.flush()
                process = subprocess.Popen(
                    command,
                    cwd=self.settings.repo_root,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                    env={
                        **os.environ,
                        "PYTHONUNBUFFERED": "1",
                        "PATH": (
                            f"{Path(self.settings.python_executable).parent}:"
                            f"{os.environ.get('PATH', '')}"
                        ),
                    },
                )
                with self._lock:
                    current = self._jobs.get(job_id)
                    if current is None or current["status"] == "deleting":
                        self._terminate_process(job_id, process)
                        continue
                    current["runtime"]["pid"] = process.pid
                    self._processes[job_id] = process
                    self._persist_locked(current)

                return_code = process.wait()

            with self._lock:
                self._processes.pop(job_id, None)
                record = self._jobs.get(job_id)
                if record is None or record["status"] == "deleting":
                    continue

                record["runtime"]["return_code"] = return_code
                record["runtime"]["pid"] = None
                record["finished_at"] = _utcnow()
                record["last_updated_at"] = _utcnow()
                scene_path = Path(record["paths"]["scene_glb"])
                if return_code == 0 and scene_path.exists():
                    record["status"] = "succeeded"
                    record["error"] = None
                    record["progress"] = {
                        "phase": "completed",
                        "label": "Job completed",
                        "overall_percent": 100.0,
                        "phase_percent": 100.0,
                        "current": 1,
                        "total": 1,
                        "queue_position": None,
                    }
                else:
                    record["status"] = "failed"
                    record["error"] = f"demo.py exited with code {return_code}"
                    record["progress"] = {
                        "phase": "failed",
                        "label": record["error"],
                        "overall_percent": record.get("progress", {}).get("overall_percent", 0.0),
                        "phase_percent": 0.0,
                        "current": 0,
                        "total": None,
                        "queue_position": None,
                    }
                self._persist_locked(record)

    def _build_command(self, record: dict) -> list[str]:
        request = record["request"]
        command = [
            self.settings.python_executable,
            str(self.settings.demo_script),
            "--model_path",
            str(self.settings.model_path),
            "--video_path",
            record["paths"]["input_video"],
            "--fps",
            str(request["fps"]),
            "--mode",
            request["mode"],
            "--num_scale_frames",
            str(request["num_scale_frames"]),
            "--export_glb",
            record["paths"]["scene_glb"],
            "--progress_path",
            record["paths"]["progress_json"],
            "--skip_viewer",
            "--sky_mask_dir",
            record["paths"]["sky_mask_dir"],
        ]
        if request["mode"] == "windowed":
            command.extend(["--window_size", str(request["window_size"])])
            command.extend(["--overlap_size", str(request["overlap_size"])])
        if request["keyframe_interval"] is not None:
            command.extend(["--keyframe_interval", str(request["keyframe_interval"])])
        if request["mask_sky"]:
            command.append("--mask_sky")
            command.extend(
                [
                    "--sky_mask_visualization_dir",
                    record["paths"]["sky_mask_visualization_dir"],
                ]
            )
        if self.settings.use_sdpa:
            command.append("--use_sdpa")
        if self.settings.offload_to_cpu:
            command.append("--offload_to_cpu")
        return command

    def _terminate_process(self, job_id: str, process: subprocess.Popen) -> None:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            except ProcessLookupError:
                pass
        with self._lock:
            record = self._jobs.get(job_id)
            if record is not None:
                record["runtime"]["pid"] = None
                record["runtime"]["return_code"] = process.returncode
                record["last_updated_at"] = _utcnow()
                self._persist_locked(record)

    def _compute_queue_position_locked(self, job_id: str) -> int | None:
        queued_ids = [
            record["job_id"]
            for record in sorted(
                self._jobs.values(),
                key=lambda item: (item.get("queued_at") or item.get("created_at") or "", item["job_id"]),
            )
            if record["status"] == "queued"
        ]
        if job_id not in queued_ids:
            return None
        return queued_ids.index(job_id) + 1

    def _load_progress_locked(self, record: dict) -> None:
        progress_path = Path(record["paths"].get("progress_json", ""))
        progress = dict(record.get("progress", {}))

        if record["status"] == "queued":
            progress["phase"] = "queued"
            progress["label"] = "Waiting for GPU worker"
            progress["overall_percent"] = 0.0
            progress["phase_percent"] = 0.0
            progress["queue_position"] = self._compute_queue_position_locked(record["job_id"])
        else:
            progress["queue_position"] = None

        if progress_path.exists():
            try:
                with progress_path.open("r", encoding="utf-8") as f:
                    progress_from_file = json.load(f)
                progress.update(progress_from_file)
            except (OSError, json.JSONDecodeError):
                pass

        record["progress"] = progress

    def _read_video_info(self, path: Path) -> dict:
        cap = cv2.VideoCapture(str(path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        cap.release()
        duration_sec = frame_count / fps if fps > 0 else None
        return {
            "fps": fps,
            "frame_count": frame_count,
            "width": width,
            "height": height,
            "duration_sec": duration_sec,
        }

    def _build_artifacts(self, record: dict) -> list[dict]:
        entries = []
        candidates = [
            ("metadata_json", "metadata.json", Path(record["paths"]["metadata_json"]), "application/json"),
            ("log_txt", "log.txt", Path(record["paths"]["log_txt"]), "text/plain"),
            ("scene_glb", "scene.glb", Path(record["paths"]["scene_glb"]), "model/gltf-binary"),
        ]
        for name, filename, path, content_type in candidates:
            if not path.exists():
                continue
            entries.append(
                {
                    "artifact_id": f"{record['job_id']}:{name}",
                    "name": name,
                    "filename": filename,
                    "path": str(path),
                    "content_type": content_type,
                    "size_bytes": path.stat().st_size,
                    "url": f"/artifacts/{record['job_id']}:{name}",
                }
            )
        return entries

    def _public_job(self, record: dict) -> dict:
        self._load_progress_locked(record)
        data = json.loads(json.dumps(record))
        data["artifacts"] = self._build_artifacts(record)
        return data

    def _persist_locked(self, record: dict) -> None:
        data = self._public_job(record)
        _json_dump(data, Path(record["paths"]["metadata_json"]))

    def _get_locked(self, job_id: str) -> dict:
        record = self._jobs.get(job_id)
        if record is None:
            raise KeyError(f"Job not found: {job_id}")
        return record


async def save_upload_to_path(upload_file, destination: Path, max_upload_bytes: int) -> tuple[int, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    hasher = hashlib.sha256()
    with destination.open("wb") as f:
        while True:
            chunk = await upload_file.read(1024 * 1024)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_upload_bytes:
                raise ValueError(f"Upload exceeds {max_upload_bytes} bytes")
            hasher.update(chunk)
            f.write(chunk)
    await upload_file.close()
    return total_bytes, hasher.hexdigest()
