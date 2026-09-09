"""Flask application factory for the audio converter."""

from __future__ import annotations

import logging
import secrets
from time import monotonic

from flask import Flask, jsonify, send_from_directory, session
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from app.api.routes import api
from app.config import Settings
from app.errors import AppError
from app.services.converter import ConversionService
from app.services.job_store import JobStore


logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or Settings.from_env()
    app = Flask(__name__, static_folder="static", static_url_path="/assets")
    app.secret_key = settings.secret_key
    app.config.update(
        MAX_CONTENT_LENGTH=settings.max_total_size,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.session_cookie_secure,
    )

    store = JobStore()
    service = ConversionService(settings, store)
    app.extensions["settings"] = settings
    app.extensions["job_store"] = store
    app.extensions["conversion_service"] = service
    app.extensions["last_cleanup"] = 0.0

    app.register_blueprint(api, url_prefix="/api")

    @app.before_request
    def initialize_browser_session() -> None:
        session.setdefault("owner_id", secrets.token_urlsafe(32))
        now = monotonic()
        if now - app.extensions["last_cleanup"] > 60:
            service.cleanup_expired()
            app.extensions["last_cleanup"] = now

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/health")
    def root_health():
        return jsonify(_health_payload(service))

    @app.errorhandler(AppError)
    def handle_app_error(error: AppError):
        return jsonify({"error": error.to_dict()}), error.status_code

    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(_error):
        return jsonify({
            "error": {
                "code": "FILE_TOO_LARGE",
                "message": "上传内容超过 500MB 限制，请减少文件数量或分批上传",
            }
        }), 413

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        return jsonify({
            "error": {
                "code": error.name.upper().replace(" ", "_"),
                "message": "请求无法完成，请检查后重试",
            }
        }), error.code or 500

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        logger.exception("unexpected application error", exc_info=error)
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务暂时出了点问题，请稍后重试",
            }
        }), 500

    return app


def _health_payload(service: ConversionService) -> dict[str, object]:
    return {
        "status": "ok",
        "ffmpeg_available": service.ffmpeg_available(),
        "ffprobe_available": service.ffprobe_available(),
    }


app = create_app()
