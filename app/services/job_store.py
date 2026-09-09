"""Thread-safe in-memory job store for the single-process MVP."""

from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create(
        self,
        *,
        job_id: str,
        owner_id: str,
        original_filename: str,
        output_filename: str,
        input_path: Path,
        output_path: Path,
        bitrate: int,
        size_bytes: int,
    ) -> dict:
        now = self._now()
        job = {
            "id": job_id,
            "owner_id": owner_id,
            "original_filename": original_filename,
            "output_filename": output_filename,
            "input_path": str(input_path),
            "output_path": str(output_path),
            "bitrate": bitrate,
            "size_bytes": size_bytes,
            "output_size_bytes": 0,
            "status": "queued",
            "progress": 0,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._jobs[job_id] = job
            return deepcopy(job)

    def get(self, job_id: str, owner_id: str | None = None) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and owner_id is not None and job["owner_id"] != owner_id:
                return None
            return deepcopy(job) if job else None

    def update(self, job_id: str, **changes: object) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job.update(changes)
            job["updated_at"] = self._now()
            return deepcopy(job)

    def delete(self, job_id: str, owner_id: str | None = None) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or (owner_id is not None and job["owner_id"] != owner_id):
                return None
            return deepcopy(self._jobs.pop(job_id))

    def expired(self, ttl_seconds: int) -> list[dict]:
        cutoff = datetime.now(timezone.utc).timestamp() - ttl_seconds
        expired_jobs: list[dict] = []
        with self._lock:
            for job in self._jobs.values():
                updated_at = datetime.fromisoformat(job["updated_at"]).timestamp()
                if updated_at < cutoff and job["status"] != "converting":
                    expired_jobs.append(deepcopy(job))
        return expired_jobs
