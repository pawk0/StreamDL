import os
import subprocess

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

from server.config import DEFAULT_ALLOWED_ORIGIN_PATTERNS, load_settings, save_settings
from server.downloader import DownloadManager, DuplicateTaskError

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static"
)
# Enable restricted CORS for local clients and browser extensions
CORS(app, resources={r"/*": {"origins": DEFAULT_ALLOWED_ORIGIN_PATTERNS}})

SAFE_MEDIA_EXTENSIONS = frozenset([
    "mp4", "mkv", "webm", "avi", "mov", "wmv", "flv", "m4v", "ts", "m2ts", "mpg", "mpeg",
    "mp3", "m4a", "flac", "wav", "aac", "ogg", "opus", "wma", "mka",
    "srt", "vtt", "ass", "ssa"
])

manager = DownloadManager.get_instance()


@app.route("/")
def index():
    settings = load_settings()
    return render_template("index.html", settings=settings)


@app.route("/api/status", methods=["GET"])
def get_status():
    settings = load_settings()
    tasks = manager.get_all_tasks()
    active = sum(1 for t in tasks if t["status"] in ["downloading", "processing"])
    queued = sum(1 for t in tasks if t["status"] == "queued")
    completed = sum(1 for t in tasks if t["status"] == "completed")
    
    return jsonify({
        "status": "online",
        "version": "1.0.0",
        "active_count": active,
        "queued_count": queued,
        "completed_count": completed,
        "total_tasks": len(tasks),
        "max_concurrent": settings.get("max_concurrent", 3),
        "max_concurrent_per_provider": settings.get("max_concurrent_per_provider", 1),
        "download_dir": settings.get("download_dir"),
    })


@app.route("/api/download", methods=["POST"])
@app.route("/download", methods=["POST"])
def queue_download():
    data = request.get_json(force=True, silent=True) or {}
    url = data.get("url")
    if not url or not isinstance(url, str) or not url.strip():
        return jsonify({"success": False, "error": "Missing or invalid 'url' parameter"}), 400

    url = url.strip()
    title = data.get("title")
    quality = data.get("quality", "best")
    fmt = data.get("format", "mp4")
    headers = dict(data.get("headers") or {})
    if data.get("referer") and not headers.get("Referer") and not headers.get("referer"):
        headers["Referer"] = data["referer"]
    provider_name = data.get("provider")
    try:
        task = manager.add_task(
            url=url,
            title=title,
            quality=quality,
            fmt=fmt,
            headers=headers,
            provider_name=provider_name,
        )
    except DuplicateTaskError as e:
        return jsonify({"success": False, "error": str(e)}), 409
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    return jsonify({
        "success": True,
        "message": f"Added to queue (Task {task.id})",
        "task": task.to_dict()
    })


@app.route("/api/queue", methods=["GET"])
def get_queue():
    settings = load_settings()
    tasks = manager.get_all_tasks()
    active_count = sum(1 for t in tasks if t["status"] in ["downloading", "processing"])
    queued_count = sum(1 for t in tasks if t["status"] == "queued")

    return jsonify({
        "tasks": tasks,
        "active_count": active_count,
        "queued_count": queued_count,
        "max_concurrent": settings.get("max_concurrent", 3),
        "max_concurrent_per_provider": settings.get("max_concurrent_per_provider", 1),
        "providers": settings.get("providers", []),
        "download_dir": settings.get("download_dir"),
    })


@app.route("/api/cancel/<task_id>", methods=["POST"])
def cancel_task(task_id: str):
    success = manager.cancel_task(task_id)
    if success:
        return jsonify({"success": True, "message": f"Task {task_id} cancelled"})
    return jsonify({"success": False, "error": "Task not found or already finished"}), 404


@app.route("/api/clear", methods=["POST"])
def clear_tasks():
    manager.clear_finished()
    return jsonify({"success": True, "message": "Cleared finished tasks"})


@app.route("/api/settings", methods=["GET", "POST"])
def manage_settings():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        updated = save_settings(data)
        manager.rematch_providers(updated)
        return jsonify({"success": True, "settings": updated})
    return jsonify({"success": True, "settings": load_settings()})


@app.route("/api/open-folder", methods=["POST"])
def open_folder():
    settings = load_settings()
    d = settings.get("download_dir")
    if not d or not isinstance(d, str):
        return jsonify({"success": False, "error": "Download directory not configured"}), 400

    base_dir = os.path.realpath(d)
    norm_base = os.path.normcase(base_dir)

    data = request.get_json(force=True, silent=True) or {}
    req_folder = data.get("folder")
    if req_folder and isinstance(req_folder, str) and req_folder.strip():
        req_folder = req_folder.strip()
        target_path = os.path.realpath(os.path.join(base_dir, req_folder)) if not os.path.isabs(req_folder) else os.path.realpath(req_folder)
        norm_target = os.path.normcase(target_path)
        try:
            if os.path.commonpath([norm_base, norm_target]) != norm_base:
                return jsonify({"success": False, "error": "Access denied: path is outside download directory"}), 403
        except ValueError:
            return jsonify({"success": False, "error": "Access denied: path is on a different drive"}), 403
    else:
        target_path = base_dir

    if not os.path.exists(target_path):
        return jsonify({"success": False, "error": "Folder does not exist"}), 404

    if not os.path.isdir(target_path):
        return jsonify({"success": False, "error": "Target path is not a directory"}), 400

    try:
        if os.name == "nt":
            os.startfile(target_path)
        else:
            subprocess.Popen(["xdg-open", target_path])
        return jsonify({"success": True, "path": target_path})
    except OSError as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/open-file/<task_id>", methods=["POST"])
def open_file(task_id: str):
    task = manager.get_task(task_id)
    if not task or not task.get("filepath"):
        return jsonify({"success": False, "error": "Filepath not recorded for this task"}), 404

    settings = load_settings()
    download_dir = settings.get("download_dir")
    if not download_dir or not isinstance(download_dir, str):
        return jsonify({"success": False, "error": "Download directory not configured"}), 400

    fp = str(task["filepath"])
    norm_base = os.path.normcase(os.path.realpath(download_dir))
    norm_fp = os.path.normcase(os.path.realpath(fp))

    try:
        if os.path.commonpath([norm_base, norm_fp]) != norm_base or norm_base == norm_fp:
            return jsonify({"success": False, "error": "Access denied: file is outside download directory"}), 403
    except ValueError:
        return jsonify({"success": False, "error": "Access denied: file is on a different drive"}), 403

    ext = os.path.splitext(norm_fp)[1].lstrip(".").lower()
    if ext not in SAFE_MEDIA_EXTENSIONS:
        return jsonify({"success": False, "error": f"Access denied: unsafe file extension '{ext}'"}), 403

    if not os.path.exists(norm_fp):
        return jsonify({"success": False, "error": f"File does not exist: {fp}"}), 404

    if not os.path.isfile(norm_fp):
        return jsonify({"success": False, "error": "Target path is not a regular file"}), 400

    try:
        if os.name == "nt":
            os.startfile(norm_fp)
        else:
            subprocess.Popen(["xdg-open", norm_fp])
        return jsonify({"success": True, "file": norm_fp})
    except OSError as e:
        return jsonify({"success": False, "error": str(e)}), 500


def run_server(port: int | None = None):
    settings = load_settings()
    if port is None:
        port = settings.get("port", 7921)
    print("=== Video Stream Downloader Server Running ===")
    print(f"Web UI: http://localhost:{port}")
    print(f"API endpoint: http://localhost:{port}/api/download")
    print(f"Downloads saved to: {settings.get('download_dir')}")
    print(f"Max concurrent downloads: {settings.get('max_concurrent', 3)}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run_server()
