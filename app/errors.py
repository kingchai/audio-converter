"""Application-level errors with safe API serialization."""

from __future__ import annotations


class AppError(Exception):
    def __init__(self, message: str, code: str = "APP_ERROR", status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class ValidationError(AppError):
    def __init__(self, message: str, code: str = "VALIDATION_ERROR") -> None:
        super().__init__(message, code, 422)


class NotFoundError(AppError):
    def __init__(self, message: str = "任务不存在或已过期") -> None:
        super().__init__(message, "NOT_FOUND", 404)


class ConflictError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "CONFLICT", 409)


class ServiceUnavailableError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "SERVICE_UNAVAILABLE", 503)
