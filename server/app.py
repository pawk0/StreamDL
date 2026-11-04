import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from server.config import DEFAULT_ALLOWED_ORIGIN_PATTERNS, load_settings, save_settings
from server.downloader import DownloadManager, DuplicateTaskError
from server.events import QueuePublisher
from server.models import (
    ActionResponse,
    DomainError,
    DownloadRequest,
    FolderRequest,
    QueueResponse,
    SettingsPatch,
    StatusResponse,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def get_manager(request: Request) -> DownloadManager:
    return request.app.state.manager


Manager = Annotated[DownloadManager, Depends(get_manager)]


SAFE_MEDIA_EXTENSIONS = frozenset(
    [
        "mp4",
        "mkv",
        "webm",
        "avi",
        "mov",
        "wmv",
        "flv",
        "m4v",
        "ts",
        "m2ts",
        "mpg",
        "mpeg",
        "mp3",
        "m4a",
        "flac",
        "wav",
        "aac",
        "ogg",
        "opus",
        "wma",
        "mka",
        "srt",
        "vtt",
        "ass",
        "ssa",
    ]
)


@router.get("/")
def index(request: Request):
    settings = load_settings()
    return templates.TemplateResponse(request, "index.html", {"settings": settings})


@router.get("/api/status", response_model=StatusResponse)
def get_status(manager: Manager):
    settings = load_settings()
    tasks = manager.get_all_tasks()
    active = sum(
        1
        for t in tasks
        if t["status"] in ["downloading", "processing", "pausing", "resuming"]
    )
    queued = sum(1 for t in tasks if t["status"] == "queued")
    completed = sum(1 for t in tasks if t["status"] == "completed")

    return {
        "status": "online",
        "version": "1.0.0",
        "active_count": active,
        "queued_count": queued,
        "completed_count": completed,
        "total_tasks": len(tasks),
        "max_concurrent": settings.get("max_concurrent", 3),
        "max_concurrent_per_provider": settings.get("max_concurrent_per_provider", 1),
        "download_dir": settings.get("download_dir"),
    }


@router.post(
    "/api/download",
    response_model=ActionResponse,
    response_model_exclude_unset=True,
    responses={400: {"model": DomainError}, 409: {"model": DomainError}},
)
@router.post(
    "/download",
    response_model=ActionResponse,
    response_model_exclude_unset=True,
    responses={400: {"model": DomainError}, 409: {"model": DomainError}},
)
def queue_download(body: DownloadRequest, manager: Manager):
    headers = dict(body.headers or {})
    if body.referer and not any(
        key.lower() == "referer" and value for key, value in headers.items()
    ):
        headers["Referer"] = body.referer
    try:
        task = manager.add_task(
            url=body.url,
            title=body.title,
            quality=body.quality,
            fmt=body.format,
            headers=headers,
            provider_name=body.provider,
        )
    except DuplicateTaskError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=409)
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)

    return {
        "success": True,
        "message": f"Added to queue (Task {task.id})",
        "task": task.to_dict(),
    }


@router.get("/api/queue", response_model=QueueResponse)
def get_queue(manager: Manager):
    return get_queue_for_manager(manager)


@router.post(
    "/api/cancel/{task_id}",
    response_model=ActionResponse,
    response_model_exclude_unset=True,
    responses={404: {"model": DomainError}},
)
def cancel_task(task_id: str, manager: Manager):
    success = manager.cancel_task(task_id)
    if success:
        return {"success": True, "message": f"Task {task_id} cancelled"}
    return JSONResponse(
        {"success": False, "error": "Task not found or already finished"},
        status_code=404,
    )


@router.post(
    "/api/pause/{task_id}",
    response_model=ActionResponse,
    response_model_exclude_unset=True,
    responses={409: {"model": DomainError}},
)
def pause_task(task_id: str, manager: Manager):
    if manager.pause_task(task_id):
        return {"success": True, "task": manager.get_task(task_id)}
    return JSONResponse(
        {"success": False, "error": "Task not found or cannot be paused"},
        status_code=409,
    )


@router.post(
    "/api/resume/{task_id}",
    response_model=ActionResponse,
    response_model_exclude_unset=True,
    responses={409: {"model": DomainError}},
)
def resume_task(task_id: str, manager: Manager):
    if manager.resume_task(task_id):
        return {"success": True, "task": manager.get_task(task_id)}
    return JSONResponse(
        {"success": False, "error": "Task not found or cannot be resumed"},
        status_code=409,
    )


@router.post(
    "/api/clear", response_model=ActionResponse, response_model_exclude_unset=True
)
def clear_tasks(manager: Manager):
    manager.clear_finished()
    return {"success": True, "message": "Cleared finished tasks"}


@router.post(
    "/api/clear/{task_id}",
    response_model=ActionResponse,
    response_model_exclude_unset=True,
    responses={409: {"model": DomainError}},
)
def clear_task(task_id: str, manager: Manager):
    if manager.clear_task(task_id):
        return {"success": True, "message": f"Task {task_id} cleared"}
    return JSONResponse(
        {"success": False, "error": "Task not found or not finished"}, status_code=409
    )


@router.get(
    "/api/settings", response_model=ActionResponse, response_model_exclude_unset=True
)
def manage_settings():
    return {"success": True, "settings": load_settings()}


@router.post(
    "/api/settings", response_model=ActionResponse, response_model_exclude_unset=True
)
def update_settings(body: SettingsPatch, manager: Manager):
    updated = save_settings(body.model_dump(exclude_unset=True))
    manager.rematch_providers(updated)
    return {"success": True, "settings": updated}


@router.post(
    "/api/open-folder",
    response_model=ActionResponse,
    response_model_exclude_unset=True,
    responses={
        400: {"model": DomainError},
        403: {"model": DomainError},
        404: {"model": DomainError},
        500: {"model": DomainError},
    },
)
def open_folder(body: FolderRequest | None = None):
    settings = load_settings()
    d = settings.get("download_dir")
    if not d or not isinstance(d, str):
        return JSONResponse(
            {"success": False, "error": "Download directory not configured"},
            status_code=400,
        )

    base_dir = os.path.realpath(d)
    norm_base = os.path.normcase(base_dir)

    data = body.model_dump() if body else {}
    req_folder = data.get("folder")
    if req_folder and isinstance(req_folder, str) and req_folder.strip():
        req_folder = req_folder.strip()
        target_path = (
            os.path.realpath(os.path.join(base_dir, req_folder))
            if not os.path.isabs(req_folder)
            else os.path.realpath(req_folder)
        )
        norm_target = os.path.normcase(target_path)
        try:
            if os.path.commonpath([norm_base, norm_target]) != norm_base:
                return JSONResponse(
                    {
                        "success": False,
                        "error": "Access denied: path is outside download directory",
                    },
                    status_code=403,
                )
        except ValueError:
            return JSONResponse(
                {
                    "success": False,
                    "error": "Access denied: path is on a different drive",
                },
                status_code=403,
            )
    else:
        target_path = base_dir

    if not os.path.exists(target_path):
        return JSONResponse(
            {"success": False, "error": "Folder does not exist"}, status_code=404
        )

    if not os.path.isdir(target_path):
        return JSONResponse(
            {"success": False, "error": "Target path is not a directory"},
            status_code=400,
        )

    try:
        if os.name == "nt":
            os.startfile(target_path)
        else:
            subprocess.Popen(["xdg-open", target_path])
        return {"success": True, "path": target_path}
    except OSError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post(
    "/api/open-file/{task_id}",
    response_model=ActionResponse,
    response_model_exclude_unset=True,
    responses={
        400: {"model": DomainError},
        403: {"model": DomainError},
        404: {"model": DomainError},
        500: {"model": DomainError},
    },
)
def open_file(task_id: str, manager: Manager):
    task = manager.get_task(task_id)
    if not task or not task.get("filepath"):
        return JSONResponse(
            {"success": False, "error": "Filepath not recorded for this task"},
            status_code=404,
        )

    settings = load_settings()
    download_dir = settings.get("download_dir")
    if not download_dir or not isinstance(download_dir, str):
        return JSONResponse(
            {"success": False, "error": "Download directory not configured"},
            status_code=400,
        )

    fp = str(task["filepath"])
    norm_base = os.path.normcase(os.path.realpath(download_dir))
    norm_fp = os.path.normcase(os.path.realpath(fp))

    try:
        if (
            os.path.commonpath([norm_base, norm_fp]) != norm_base
            or norm_base == norm_fp
        ):
            return JSONResponse(
                {
                    "success": False,
                    "error": "Access denied: file is outside download directory",
                },
                status_code=403,
            )
    except ValueError:
        return JSONResponse(
            {"success": False, "error": "Access denied: file is on a different drive"},
            status_code=403,
        )

    ext = os.path.splitext(norm_fp)[1].lstrip(".").lower()
    if ext not in SAFE_MEDIA_EXTENSIONS:
        return JSONResponse(
            {
                "success": False,
                "error": f"Access denied: unsafe file extension '{ext}'",
            },
            status_code=403,
        )

    if not os.path.exists(norm_fp):
        return JSONResponse(
            {"success": False, "error": f"File does not exist: {fp}"}, status_code=404
        )

    if not os.path.isfile(norm_fp):
        return JSONResponse(
            {"success": False, "error": "Target path is not a regular file"},
            status_code=400,
        )

    try:
        if os.name == "nt":
            os.startfile(norm_fp)
        else:
            subprocess.Popen(["xdg-open", norm_fp])
        return {"success": True, "file": norm_fp}
    except OSError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


def create_app(manager: DownloadManager | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        import asyncio

        active_manager = manager or DownloadManager()
        application.state.manager = active_manager
        publisher = QueuePublisher(lambda: get_queue_for_manager(active_manager))
        application.state.publisher = publisher
        active_manager.start()
        try:
            yield
        finally:
            await publisher.stop()
            await asyncio.to_thread(active_manager.stop)

    application = FastAPI(title="StreamDL", version="1.0.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origin_regex="(?:" + "|".join(DEFAULT_ALLOWED_ORIGIN_PATTERNS) + ")",
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    application.include_router(router)
    application.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="static",
    )
    return application


def get_queue_for_manager(manager: DownloadManager) -> dict:
    settings = load_settings()
    tasks = manager.get_all_tasks()
    return QueueResponse.model_validate(
        {
            "tasks": tasks,
            "active_count": sum(
                t["status"] in {"downloading", "processing", "pausing", "resuming"}
                for t in tasks
            ),
            "queued_count": sum(t["status"] == "queued" for t in tasks),
            "max_concurrent": settings.get("max_concurrent", 3),
            "max_concurrent_per_provider": settings.get(
                "max_concurrent_per_provider", 1
            ),
            "providers": settings.get("providers", []),
            "download_dir": settings.get("download_dir"),
        }
    ).model_dump()


@router.get("/api/events", response_class=EventSourceResponse)
async def events(request: Request):
    async for event in request.app.state.publisher.stream():
        yield event


app = create_app()


class StreamDLServer(uvicorn.Server):
    async def shutdown(self, sockets=None):
        # End SSE responses before Uvicorn waits for active requests to drain.
        application = self.config.app
        publisher = getattr(application.state, "publisher", None) if isinstance(application, FastAPI) else None
        if publisher is not None:
            await publisher.stop()
        await super().shutdown(sockets=sockets)


def run_server(port: int | None = None):
    settings = load_settings()
    if port is None:
        port = settings.get("port", 7921)
    print(f"StreamDL: http://localhost:{port}")
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        workers=1,
        reload=False,
        timeout_graceful_shutdown=1,
    )
    StreamDLServer(config).run()


if __name__ == "__main__":
    run_server()
