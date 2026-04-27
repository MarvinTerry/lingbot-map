from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse

from lingbot_map_server.config import ServerSettings, load_settings
from lingbot_map_server.job_manager import JobManager, save_upload_to_path


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    settings: ServerSettings = request.app.state.settings
    if x_api_key == settings.api_key:
        return
    if authorization == f"Bearer {settings.api_key}":
        return
    raise HTTPException(status_code=401, detail="Invalid API key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    manager = JobManager(settings)
    manager.start()
    app.state.settings = settings
    app.state.manager = manager
    try:
        yield
    finally:
        manager.stop()


app = FastAPI(title="LingBot-Map Server", version="0.1.0", lifespan=lifespan)
APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
app.mount("/ui-static", StaticFiles(directory=str(APP_DIR / "static")), name="ui-static")


def _manager(request: Request) -> JobManager:
    return request.app.state.manager


def _validate_mode(mode: str) -> None:
    if mode not in {"streaming", "windowed"}:
        raise HTTPException(status_code=422, detail="mode must be 'streaming' or 'windowed'")


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/upload", status_code=307)


@app.get("/ui")
def ui_root() -> RedirectResponse:
    return RedirectResponse(url="/ui/workspace", status_code=307)


@app.get("/ui/workspace")
def workspace_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="workspace.html",
        context={
            "request": request,
            "selected_job_id": request.query_params.get("job_id", ""),
        },
    )


@app.get("/ui/upload")
def upload_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={
            "request": request,
            "max_upload_bytes": request.app.state.settings.max_upload_bytes,
        },
    )


@app.get("/ui/jobs/{job_id}")
def job_page(job_id: str, request: Request):
    del request
    return RedirectResponse(url=f"/ui/workspace?job_id={job_id}", status_code=307)


@app.get("/ui/jobs/{job_id}/preview")
def job_preview_page(job_id: str, request: Request):
    manager = _manager(request)
    try:
        job = manager.get_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    preview = job.get("preview", {})
    port = preview.get("port")
    if preview.get("status") != "ready" or not port:
        message = preview.get("error") or "Preview is not ready yet."
        return HTMLResponse(
            f"<html><body><pre>{message}</pre></body></html>",
            status_code=503,
        )

    host = request.url.hostname or "127.0.0.1"
    return RedirectResponse(url=f"http://{host}:{port}/", status_code=307)


@app.get("/healthz")
def healthz(request: Request) -> dict:
    settings: ServerSettings = request.app.state.settings
    return {
        "status": "ok",
        "model_path": str(settings.model_path),
        "jobs_dir": str(settings.jobs_dir),
        "max_upload_bytes": settings.max_upload_bytes,
    }


@app.post("/jobs", status_code=201, dependencies=[Depends(require_api_key)])
async def create_job(
    request: Request,
    file: UploadFile = File(...),
    fps: int = Form(10),
    mode: str = Form("streaming"),
    window_size: int = Form(64),
    overlap_size: int = Form(16),
    keyframe_interval: int | None = Form(None),
    num_scale_frames: int = Form(8),
    mask_sky: bool = Form(False),
) -> dict:
    _validate_mode(mode)
    if not file.filename or not file.filename.lower().endswith(".mp4"):
        raise HTTPException(status_code=400, detail="Only .mp4 uploads are supported in Phase 1")
    if fps <= 0 or window_size <= 0 or overlap_size < 0 or num_scale_frames <= 0:
        raise HTTPException(status_code=422, detail="Invalid numeric request parameters")
    if keyframe_interval is not None and keyframe_interval <= 0:
        raise HTTPException(status_code=422, detail="keyframe_interval must be positive")

    manager = _manager(request)
    job = manager.reserve_job(
        filename=file.filename,
        content_type=file.content_type,
        request_params={
            "fps": fps,
            "mode": mode,
            "window_size": window_size,
            "overlap_size": overlap_size,
            "keyframe_interval": keyframe_interval,
            "num_scale_frames": num_scale_frames,
            "mask_sky": mask_sky,
        },
    )

    try:
        size_bytes, sha256 = await save_upload_to_path(
            file,
            Path(job["paths"]["input_video"]),
            manager.settings.max_upload_bytes,
        )
        return manager.complete_upload(job["job_id"], size_bytes, sha256)
    except ValueError as e:
        manager.delete_job(job["job_id"])
        raise HTTPException(status_code=413, detail=str(e)) from e
    except Exception as e:
        manager.fail_upload(job["job_id"], str(e))
        manager.delete_job(job["job_id"])
        raise HTTPException(status_code=500, detail=f"Failed to store upload: {e}") from e


@app.get("/jobs/{job_id}", dependencies=[Depends(require_api_key)])
def get_job(job_id: str, request: Request) -> dict:
    manager = _manager(request)
    try:
        return manager.get_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/jobs", dependencies=[Depends(require_api_key)])
def get_jobs(request: Request) -> dict:
    manager = _manager(request)
    return {"jobs": manager.list_jobs()}


@app.get("/jobs/{job_id}/artifacts", dependencies=[Depends(require_api_key)])
def list_artifacts(job_id: str, request: Request) -> dict:
    manager = _manager(request)
    try:
        return {"job_id": job_id, "artifacts": manager.list_artifacts(job_id)}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.delete("/jobs/{job_id}", dependencies=[Depends(require_api_key)], status_code=204)
def delete_job(job_id: str, request: Request) -> Response:
    manager = _manager(request)
    try:
        manager.delete_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(status_code=204)


@app.get("/artifacts/{artifact_id}", dependencies=[Depends(require_api_key)])
def get_artifact(artifact_id: str, request: Request) -> FileResponse:
    manager = _manager(request)
    try:
        path, content_type = manager.resolve_artifact(artifact_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return FileResponse(path, media_type=content_type, filename=path.name)
