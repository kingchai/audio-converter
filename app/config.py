"""Environment-backed application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"环境变量 {name} 必须是整数") from exc
    if value <= 0:
        raise RuntimeError(f"环境变量 {name} 必须大于 0")
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    job_dir: Path
    ffmpeg_bin: str
    ffprobe_bin: str
    secret_key: str
    session_cookie_secure: bool
    max_file_size: int
    max_total_size: int
    max_files: int
    job_ttl_seconds: int
    conversion_timeout_seconds: int
    max_workers: int
    bitrate_options: tuple[int, ...] = (128, 192, 320)

    @classmethod
    def from_env(cls) -> "Settings":
        job_dir = Path(os.getenv("JOB_DIR", str(PROJECT_ROOT / "instance" / "jobs"))).expanduser()
        return cls(
            job_dir=job_dir,
            ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg"),
            ffprobe_bin=os.getenv("FFPROBE_BIN", "ffprobe"),
            secret_key=os.getenv("SECRET_KEY", "change-this-secret-before-production"),
            session_cookie_secure=_env_bool("SESSION_COOKIE_SECURE"),
            max_file_size=_env_int("MAX_FILE_SIZE", 200 * 1024 * 1024),
            max_total_size=_env_int("MAX_TOTAL_SIZE", 500 * 1024 * 1024),
            max_files=_env_int("MAX_FILES", 10),
            job_ttl_seconds=_env_int("JOB_TTL_SECONDS", 30 * 60),
            conversion_timeout_seconds=_env_int("CONVERSION_TIMEOUT_SECONDS", 900),
            max_workers=_env_int("MAX_WORKERS", 2),
        )
