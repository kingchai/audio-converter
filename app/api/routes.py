"""HTTP routes for audio conversion jobs."""

from __future__ import annotations

import io
import threading
from collections import defaultdict, deque
from time import monotonic
from zipfile import ZIP_DEFLATED, ZipFile

from flask import Blueprint, current_app, jsonify, request, send_file, session
from werkzeug.exceptions import RequestEntityTooLarge

from app.errors import AppError, NotFoundError, ValidationError
from app.services.converter import SUPPORTED_EXTENSIONS

api = Blueprint("api", __name__)
_rate_windows: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = threading.Lock()


def _service():
    return current_app.extensions["conversion_service"]


def _settings():
    return current_app.extensions["settings"]


def _owner_id() -> str:
    return session["owner_id"]


def _check_rate_limit() -> None:
    address = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    now = monotonic()
    with _rate_lock:
        window = _rate_windows[address]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= 30:
            raise AppError("操作太频繁，请稍后再试", "RATE_LIMITED", 429)
        window.append(now)


@api.get("/health")
def health():
    service = _service()
    return jsonify({
        "status": "ok",
        "ffmpeg_available": service.ffmpeg_available(),
        "ffprobe_available": service.ffprobe_available(),
    })


@api.get("/capabilities")
def capabilities():
    settings = _settings()
    return jsonify({
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
        "bitrate_options": list(settings.bitrate_options),
        "max_file_size": settings.max_file_size,
        "max_total_size": settings.max_total_size,
        "max_files": settings.max_files,
    })


@api.post("/convert")
def create_conversion():
    _check_rate_limit()
    files = request.files.getlist("files") or request.files.getlist("file")
    files = [item for item in files if (item.filename or "").strip()]
    if not files:
        raise ValidationError("请选择要转换的音频文件")

    settings = _settings()
    if len(files) > settings.max_files:
        raise ValidationError(f"一次最多上传 {settings.max_files} 个文件")
    try:
        bitrate = int(request.form.get("bitrate", "192"))
    except ValueError as exc:
        raise ValidationError("音质参数无效，请选择 128、192 或 320 kbps") from exc

    owner_id = _owner_id()
    jobs = _service().create_jobs(files, bitrate, owner_id)
    return jsonify({"data": jobs}), 202


@api.get("/convert/<job_id>")
def get_conversion(job_id: str):
    job = _service().get_job(job_id, _owner_id())
    if not job:
        raise NotFoundError()
    return jsonify({"data": job})


@api.delete("/convert/<job_id>")
def delete_conversion(job_id: str):
    if not _service().delete_job(job_id, _owner_id()):
        raise NotFoundError()
    return jsonify({"data": {"deleted": True}})


@api.get("/download/<job_id>")
def download_conversion(job_id: str):
    job, output_path = _service().output_path(job_id, _owner_id())
    return send_file(
        output_path,
        as_attachment=True,
        download_name=job["output_filename"],
        mimetype="audio/mpeg",
        max_age=0,
    )


@api.post("/download-batch")
def download_batch():
    _check_rate_limit()
    payload = request.get_json(silent=True) or {}
    job_ids = payload.get("job_ids")
    if not isinstance(job_ids, list) or not job_ids or len(job_ids) > _settings().max_files:
        raise ValidationError("请选择需要下载的转换结果")

    job_paths = _service().bundle_paths(job_ids, _owner_id())
    archive = io.BytesIO()
    used_names: set[str] = set()
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        for job, output_path in job_paths:
            filename = job["output_filename"]
            if filename in used_names:
                stem = filename.rsplit(".", 1)[0]
                filename = f"{stem}-{job['id'][:6]}.mp3"
            used_names.add(filename)
            bundle.write(output_path, arcname=filename)
    archive.seek(0)
    return send_file(
        archive,
        as_attachment=True,
        download_name="sonora-mp3-files.zip",
        mimetype="application/zip",
        max_age=0,
    )


@api.app_errorhandler(RequestEntityTooLarge)
def handle_too_large(_error):
    return jsonify({"error": {"code": "FILE_TOO_LARGE", "message": "上传内容超过 500MB 限制"}}), 413
