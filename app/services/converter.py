"""FFmpeg conversion orchestration."""

from __future__ import annotations

import os
import selectors
import shutil
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic

from app.config import Settings
from app.errors import ConflictError, NotFoundError, ServiceUnavailableError, ValidationError
from app.services.job_store import JobStore


SUPPORTED_EXTENSIONS = {
    ".wav", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".wma",
    ".aiff", ".aif", ".mp3", ".mp4", ".mov", ".webm",
}


class ConversionService:
    def __init__(self, settings: Settings, store: JobStore) -> None:
        self.settings = settings
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=settings.max_workers, thread_name_prefix="audio-convert")
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._process_lock = threading.RLock()
        self.settings.job_dir.mkdir(parents=True, exist_ok=True)

    def ffmpeg_available(self) -> bool:
        return bool(shutil.which(self.settings.ffmpeg_bin) or Path(self.settings.ffmpeg_bin).is_file())

    def ffprobe_available(self) -> bool:
        return bool(shutil.which(self.settings.ffprobe_bin) or Path(self.settings.ffprobe_bin).is_file())

    def ensure_ready(self) -> None:
        if not self.ffmpeg_available() or not self.ffprobe_available():
            raise ServiceUnavailableError("服务器尚未配置 FFmpeg，请联系管理员完成音频转换组件安装")

    def validate_extension(self, filename: str) -> None:
        if Path(filename.replace("\\", "/")).suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValidationError("暂不支持该格式，请上传 WAV、M4A、AAC、FLAC、OGG、WMA 或常见视频文件")

    def create_job(self, file_storage, bitrate: int, owner_id: str) -> dict:
        return self.create_jobs([file_storage], bitrate, owner_id)[0]

    def create_jobs(self, file_storages: list, bitrate: int, owner_id: str) -> list[dict]:
        self.ensure_ready()
        if bitrate not in self.settings.bitrate_options:
            raise ValidationError("音质参数无效，请选择 128、192 或 320 kbps")
        if not file_storages:
            raise ValidationError("请选择要转换的音频文件")
        if len(file_storages) > self.settings.max_files:
            raise ValidationError(f"一次最多上传 {self.settings.max_files} 个文件")

        prepared: list[dict] = []
        total_size = 0
        try:
            for file_storage in file_storages:
                item = self._prepare_file(file_storage, bitrate, owner_id)
                prepared.append(item)
                total_size += item["size_bytes"]
                if total_size > self.settings.max_total_size:
                    raise ValidationError("本次上传总大小不能超过 500MB", "TOTAL_FILE_TOO_LARGE")
        except Exception:
            for item in prepared:
                self._remove_paths(item["input_path"], item["output_path"])
            raise

        jobs = [self.store.create(**item) for item in prepared]
        for job in jobs:
            self.executor.submit(self._convert, job["id"])
        return [self.public_job(job) for job in jobs]

    def get_job(self, job_id: str, owner_id: str) -> dict | None:
        return self.public_job(self.store.get(job_id, owner_id))

    def delete_job(self, job_id: str, owner_id: str) -> bool:
        job = self.store.get(job_id, owner_id)
        if not job:
            return False
        if job["status"] == "converting":
            raise ConflictError("文件正在转换，请稍后再删除")
        self._remove_paths(Path(job["input_path"]), Path(job["output_path"]))
        return bool(self.store.delete(job_id, owner_id))

    def bundle_paths(self, job_ids: list[str], owner_id: str) -> list[tuple[dict, Path]]:
        results: list[tuple[dict, Path]] = []
        for job_id in dict.fromkeys(job_ids):
            job = self.store.get(job_id, owner_id)
            if not job:
                raise NotFoundError()
            if job["status"] != "success" or not Path(job["output_path"]).is_file():
                raise ValidationError("部分文件还没有转换完成，请稍后再试", "NOT_READY")
            results.append((job, Path(job["output_path"])))
        return results

    def cleanup_expired(self) -> int:
        count = 0
        for job in self.store.expired(self.settings.job_ttl_seconds):
            self._remove_paths(Path(job["input_path"]), Path(job["output_path"]))
            if self.store.delete(job["id"]):
                count += 1
        return count

    @staticmethod
    def public_job(job: dict | None) -> dict | None:
        if not job:
            return None
        return {key: job[key] for key in (
            "id", "original_filename", "output_filename", "bitrate", "size_bytes",
            "output_size_bytes", "status", "progress", "error", "created_at", "updated_at",
        )}

    def output_path(self, job_id: str, owner_id: str) -> tuple[dict, Path]:
        job = self.store.get(job_id, owner_id)
        if not job:
            raise NotFoundError()
        if job["status"] != "success":
            raise ValidationError("文件还没有转换完成，请稍后再试", "NOT_READY")
        path = Path(job["output_path"])
        if not path.is_file():
            raise ValidationError("转换文件已过期，请重新上传", "FILE_EXPIRED")
        return job, path

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _prepare_file(self, file_storage, bitrate: int, owner_id: str) -> dict:
        raw_name = (file_storage.filename or "").strip()
        if not raw_name:
            raise ValidationError("请选择一个有效的音频文件")
        client_name = raw_name.replace("\\", "/").rsplit("/", 1)[-1]
        self.validate_extension(client_name)

        job_id = uuid.uuid4().hex
        suffix = Path(client_name).suffix.lower()
        input_path = self.settings.job_dir / f"{job_id}{suffix}"
        output_path = self.settings.job_dir / f"{job_id}.mp3"
        file_storage.save(input_path)
        size_bytes = input_path.stat().st_size
        if size_bytes == 0:
            self._remove_paths(input_path)
            raise ValidationError("文件为空，请重新选择音频")
        if size_bytes > self.settings.max_file_size:
            self._remove_paths(input_path)
            raise ValidationError("单个文件不能超过 200MB")
        try:
            self._probe(input_path)
        except Exception:
            self._remove_paths(input_path)
            raise

        stem = Path(client_name).stem.strip().strip(".")
        stem = "".join(char for char in stem if char >= " " and char not in "/\\")[:120] or "converted"
        return {
            "job_id": job_id,
            "owner_id": owner_id,
            "original_filename": client_name,
            "output_filename": f"{stem}.mp3",
            "input_path": input_path,
            "output_path": output_path,
            "bitrate": bitrate,
            "size_bytes": size_bytes,
        }

    def _probe(self, input_path: Path) -> None:
        try:
            result = subprocess.run([
                self.settings.ffprobe_bin, "-v", "error", "-show_entries", "format=format_name",
                "-of", "default=noprint_wrappers=1:nokey=1", str(input_path),
            ], capture_output=True, text=True, timeout=30, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ValidationError("文件检测超时，请确认文件没有损坏") from exc
        if result.returncode != 0 or not result.stdout.strip():
            raise ValidationError("无法读取这个文件，请确认格式正确且文件没有损坏")

    def _duration(self, input_path: str) -> float:
        try:
            result = subprocess.run([
                self.settings.ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", input_path,
            ], capture_output=True, text=True, timeout=30, check=False)
            return max(float(result.stdout.strip()), 0.0)
        except (OSError, TypeError, ValueError, subprocess.SubprocessError):
            return 0.0

    def _convert(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if not job:
            return
        input_path, output_path = job["input_path"], job["output_path"]
        duration = self._duration(input_path)
        self.store.update(job_id, status="converting", progress=1)
        command = [
            self.settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", "-i", input_path,
            "-vn", "-map_metadata", "0", "-codec:a", "libmp3lame", "-b:a", f"{job['bitrate']}k",
            "-id3v2_version", "3", "-progress", "pipe:1", "-nostats", output_path,
        ]
        process: subprocess.Popen[str] | None = None
        errors: list[str] = []
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            with self._process_lock:
                self._processes[job_id] = process
            assert process.stdout is not None
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = monotonic() + self.settings.conversion_timeout_seconds
            while process.poll() is None:
                if monotonic() > deadline:
                    process.kill()
                    raise subprocess.TimeoutExpired(command, self.settings.conversion_timeout_seconds)
                for key, _ in selector.select(timeout=0.35):
                    line = key.fileobj.readline().strip()
                    if line.startswith("out_time_ms="):
                        try:
                            seconds = int(line.split("=", 1)[1]) / 1_000_000
                        except ValueError:
                            continue
                        if duration:
                            self.store.update(job_id, progress=min(98, max(1, int(seconds / duration * 100))))
                    elif line and not line.startswith("progress="):
                        errors.append(line)
                        errors = errors[-20:]
            for line in process.stdout.read().splitlines():
                if line and not line.startswith(("out_time_ms=", "progress=")):
                    errors.append(line)
            return_code = process.returncode
            if return_code != 0:
                details = "\n".join(errors)
                message = "这个文件暂时无法转换，请确认文件没有损坏后重试"
                if "Invalid data" in details or "could not find codec" in details:
                    message = "无法识别该音频编码，请更换文件后重试"
                self._remove_paths(Path(output_path))
                self.store.update(job_id, status="error", progress=0, error=message)
                return
            output_size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0
            if output_size == 0:
                self.store.update(job_id, status="error", progress=0, error="转换未生成有效的 MP3 文件")
                return
            self.store.update(job_id, status="success", progress=100, output_size_bytes=output_size, error=None)
        except subprocess.TimeoutExpired:
            if process:
                process.kill()
            self._remove_paths(Path(output_path))
            self.store.update(job_id, status="error", progress=0, error="转换时间过长，请尝试较小的文件")
        except (OSError, ValueError, subprocess.SubprocessError):
            self._remove_paths(Path(output_path))
            self.store.update(job_id, status="error", progress=0, error="转换服务暂时不可用，请稍后重试")
        finally:
            with self._process_lock:
                self._processes.pop(job_id, None)
            self._remove_paths(Path(input_path))

    @staticmethod
    def _remove_paths(*paths: Path) -> None:
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
