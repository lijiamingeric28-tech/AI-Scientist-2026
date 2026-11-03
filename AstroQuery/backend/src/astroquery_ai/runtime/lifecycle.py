"""A process lock prevents two schedulers opening the same runtime root."""

from pathlib import Path

from .errors import DomainError


class InstanceLock:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "instance.lock"
        self.handle = None

    def acquire(self):
        import os

        self.handle = self.path.open("a+b")
        self.handle.seek(0, 2)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise DomainError("INSTANCE_ALREADY_RUNNING", "此数据目录已有运行实例") from exc
        return self

    def release(self):
        if self.handle:
            import os

            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle, fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.release()
