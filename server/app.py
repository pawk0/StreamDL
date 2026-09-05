import os
import subprocess
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS

from server.config import load_settings, save_settings
from server.downloader import DownloadManager

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static"
)
# Enable CORS for all routes (necessary for browser extensions and local clients)
CORS(app, resources={r"/*": {"origins": "*"}})

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
    headers = data.get("headers", {})
    provider_name = data.get("provider")

    task = manager.add_task(
        url=url,
        title=title,
        quality=quality,
        fmt=fmt,
        headers=headers,
        provider_name=provider_name,
    )

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
        return jsonify({"success": True, "settings": updated})
    return jsonify({"success": True, "settings": load_settings()})


@app.route("/api/open-folder", methods=["POST"])
def open_folder():
    settings = load_settings()
    d = settings.get("download_dir")
    if os.path.exists(d):
        try:
            if os.name == "nt":
                os.startfile(d)
            else:
                subprocess.Popen(["xdg-open", d])
            return jsonify({"success": True, "path": d})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    return jsonify({"success": False, "error": "Folder does not exist"}), 404


@app.route("/api/open-file/<task_id>", methods=["POST"])
def open_file(task_id: str):
    task = manager.get_task(task_id)
    if not task or not task.get("filepath"):
        return jsonify({"success": False, "error": "Filepath not recorded for this task"}), 404
    
    fp = task["filepath"]
    if os.path.exists(fp):
        try:
            if os.name == "nt":
                os.startfile(fp)
            else:
                subprocess.Popen(["xdg-open", fp])
            return jsonify({"success": True, "file": fp})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    return jsonify({"success": False, "error": f"File does not exist: {fp}"}), 404


def run_server():
    settings = load_settings()
    port = settings.get("port", 7921)
    print(f"=== Video Stream Downloader Server Running ===")
    print(f"Web UI: http://localhost:{port}")
    print(f"API endpoint: http://localhost:{port}/api/download")
    print(f"Downloads saved to: {settings.get('download_dir')}")
    print(f"Max concurrent downloads: {settings.get('max_concurrent', 3)}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run_server()
