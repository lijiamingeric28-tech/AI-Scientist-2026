"""Content addressed immutable artifacts; callers register task ownership in DB."""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
from pathlib import Path
from uuid import uuid4

from .codec import utcnow
from .errors import DomainError


class ArtifactStore:
    def __init__(self, root: Path, repository, max_bytes=20 * 1024**3):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.repository, self.max_bytes = repository, max_bytes
        self._pending, self._pending_lock = {}, threading.Lock()

    def path(self, relative_path: str) -> Path:
        result = (self.root / relative_path).resolve()
        if not result.is_relative_to(self.root) or result == self.root:
            raise DomainError("INVALID_ARTIFACT_PATH", "文件路径超出数据目录", 422)
        return result

    def write(self, data: bytes, media_type: str, *, repair_corrupt=False) -> dict:
        if not isinstance(data, bytes):
            raise TypeError("artifact must be bytes")
        sha = hashlib.sha256(data).hexdigest()
        if data.startswith(b"%PDF-"):
            media_type = "application/pdf"
        elif data.startswith(b"\x89PNG\r\n\x1a\n"):
            media_type = "image/png"
        relative = f"objects/{sha[:2]}/{sha}"
        path = self.path(relative)
        staging = uuid4().hex
        with self.repository.transaction() as conn:
            used = conn.execute(
                "SELECT coalesce(sum(byte_size),0) FROM artifacts WHERE availability<>'missing'"
            ).fetchone()[0]
            existing = conn.execute(
                "SELECT availability FROM artifacts WHERE artifact_id=?", (sha,)
            ).fetchone()
            extra = 0 if existing and existing[0] != "missing" else len(data)
            if (
                used + extra > self.max_bytes
                or shutil.disk_usage(self.root).free - extra < 512 * 1024**2
            ):
                raise DomainError("STORAGE_EXHAUSTED", "存储额度或磁盘余量不足")
            conn.execute(
                "INSERT INTO artifacts(artifact_id,sha256,byte_size,relative_path,media_type,created_at,availability) VALUES(?,?,?,?,?,?,'reserved') ON CONFLICT(artifact_id) DO UPDATE SET availability=CASE WHEN availability='missing' THEN 'reserved' ELSE availability END",
                (sha, sha, len(data), relative, media_type, utcnow()),
            )
            conn.execute(
                "INSERT INTO artifact_leases VALUES(?,?,?,?)",
                (staging, sha, "staging-write", time.time() + 600),
            )
        if path.exists():
            if (
                path.stat().st_size != len(data)
                or hashlib.sha256(path.read_bytes()).hexdigest() != sha
            ):
                if not repair_corrupt:
                    raise DomainError("CORRUPT_ARTIFACT", "已保存原件的内容不匹配")
                # Explicit cache recovery only: fresh bytes already hash to
                # the exact original identity. Preserve damaged bytes; never
                # rewrite source records or another runtime's cache.
                quarantine=self.path('quarantine/'+sha+'-'+uuid4().hex)
                quarantine.parent.mkdir(parents=True,exist_ok=True)
                os.replace(path,quarantine)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(sha + "." + uuid4().hex + ".tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        with self.repository.transaction() as conn:
            conn.execute("UPDATE artifacts SET availability='ready' WHERE artifact_id=?", (sha,))
        with self._pending_lock:
            self._pending.setdefault(sha, []).append(staging)
        return {
            "artifact_id": sha,
            "sha256": sha,
            "byte_size": len(data),
            "relative_path": relative,
            "media_type": media_type,
        }

    def register(self, conn, task_id: str, owner_id: str, artifact: dict):
        self.repository.task(conn, task_id)
        path = self.path(artifact["relative_path"])
        if (
            not path.is_file()
            or path.stat().st_size != artifact["byte_size"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]
        ):
            raise DomainError("ARTIFACT_NOT_READY", "原件尚未完整保存或校验失败")
        conn.execute(
            "INSERT INTO artifacts(artifact_id,sha256,byte_size,relative_path,media_type,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(artifact_id) DO UPDATE SET availability='ready'",
            (
                *[
                    artifact[k]
                    for k in ("artifact_id", "sha256", "byte_size", "relative_path", "media_type")
                ],
                utcnow(),
            ),
        )
        conn.execute(
            "INSERT OR IGNORE INTO artifact_refs VALUES(?,?,?)",
            (task_id, artifact["artifact_id"], owner_id),
        )
        with self._pending_lock:
            pending = self._pending.get(artifact["artifact_id"], [])
            if pending:
                conn.execute("DELETE FROM artifact_leases WHERE lease_id=?", (pending.pop(0),))

    def read_owned(self, task_id: str, artifact_id: str) -> tuple[dict, Path]:
        with self.repository.read() as conn:
            self.repository.task(conn, task_id)
            row = conn.execute(
                "SELECT a.* FROM artifacts a JOIN artifact_refs r USING(artifact_id) WHERE r.task_id=? AND a.artifact_id=?",
                (task_id, artifact_id),
            ).fetchone()
            if row is None:
                raise DomainError("ARTIFACT_NOT_FOUND", "该任务没有此文件", 404)
            artifact = dict(row)
        path = self.path(artifact["relative_path"])
        if not path.is_file():
            raise DomainError("ARTIFACT_MISSING", "原件已不可用", 410)
        if (
            path.stat().st_size != artifact["byte_size"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]
        ):
            raise DomainError("ARTIFACT_CORRUPT", "文件校验失败", 410)
        return artifact, path

    def lease(self, task_id, artifact_id, *, seconds=600):
        import time
        from .codec import new_id

        with self.repository.transaction() as conn:
            self.repository.task(conn, task_id)
            if not conn.execute(
                "SELECT 1 FROM artifact_refs WHERE task_id=? AND artifact_id=?",
                (task_id, artifact_id),
            ).fetchone():
                raise DomainError("ARTIFACT_NOT_FOUND", "该任务没有此原件", 404)
            lease_id = new_id()
            conn.execute(
                "INSERT INTO artifact_leases VALUES(?,?,?,?)",
                (lease_id, artifact_id, task_id, time.time() + seconds),
            )
        return lease_id

    def release(self, lease_id):
        with self.repository.transaction() as conn:
            conn.execute("DELETE FROM artifact_leases WHERE lease_id=?", (lease_id,))
