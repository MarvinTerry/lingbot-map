from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys

from dotenv import load_dotenv


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_dotenv_files(repo_root: Path | None = None) -> Path:
    resolved_repo_root = repo_root or Path(__file__).resolve().parents[1]
    load_dotenv(resolved_repo_root / ".env", override=False)
    return resolved_repo_root


@dataclass(frozen=True)
class ServerSettings:
    api_key: str
    model_path: Path
    repo_root: Path
    jobs_dir: Path
    max_upload_bytes: int
    python_executable: str
    use_sdpa: bool
    offload_to_cpu: bool
    preview_port_base: int
    preview_max_frames: int
    preview_spatial_stride: int

    @property
    def demo_script(self) -> Path:
        return self.repo_root / "demo.py"


def load_settings() -> ServerSettings:
    repo_root = load_dotenv_files()
    model_path_value = os.getenv("LINGBOT_MAP_MODEL_PATH", "").strip()
    api_key = os.getenv("LINGBOT_MAP_SERVER_API_KEY", "").strip()
    jobs_dir = Path(
        os.getenv("LINGBOT_MAP_SERVER_JOBS_DIR", str(repo_root / "outputs" / "jobs"))
    ).expanduser()

    if not api_key:
        raise RuntimeError("LINGBOT_MAP_SERVER_API_KEY is required.")
    if not model_path_value:
        raise RuntimeError("LINGBOT_MAP_MODEL_PATH is required.")
    model_path = Path(model_path_value).expanduser()
    if not model_path.exists():
        raise RuntimeError(f"Model checkpoint not found: {model_path}")

    return ServerSettings(
        api_key=api_key,
        model_path=model_path,
        repo_root=repo_root,
        jobs_dir=jobs_dir,
        max_upload_bytes=4 * 1024 ** 3,
        python_executable=sys.executable,
        use_sdpa=_env_bool("LINGBOT_MAP_SERVER_USE_SDPA", False),
        offload_to_cpu=_env_bool("LINGBOT_MAP_SERVER_OFFLOAD_TO_CPU", True),
        preview_port_base=int(os.getenv("LINGBOT_MAP_SERVER_PREVIEW_PORT_BASE", "9000")),
        preview_max_frames=int(os.getenv("LINGBOT_MAP_SERVER_PREVIEW_MAX_FRAMES", "96")),
        preview_spatial_stride=int(os.getenv("LINGBOT_MAP_SERVER_PREVIEW_SPATIAL_STRIDE", "4")),
    )
