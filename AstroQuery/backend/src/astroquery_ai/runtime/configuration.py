"""Validated, atomically saved local secrets; public views never return keys."""

from __future__ import annotations

import csv
import os
import re
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from .codec import canonical, loads, digest
from .errors import DomainError

SECRET_FIELDS = {"dashscope_api_key", "ads_api_token"}
REQUIRED_CONNECTION_FIELDS = SECRET_FIELDS | {"dashscope_base_url", "unpaywall_email"}
EDITABLE = REQUIRED_CONNECTION_FIELDS | {"ads_sort", "literature_papers_per_property", "retrieval_policy_version", "research_delivery_version"}
MODELS = {
    "text": "qwen3.8-flash",
    "vision": "qwen3.7-plus",
    "normalization": "qwen3.8-flash",
    "property": "qwen3.8-max",
    "insight": "qwen3.8-max",
    "material_summary": "qwen3.8-flash",
    "copilot": "qwen3.8-max",
}
_CONFIG_LOCKS = {}


@contextmanager
def config_lock(root):
    """Serialize GUI saves and CLI imports, including independent processes."""
    lock = _CONFIG_LOCKS.setdefault(str(root), threading.RLock())
    with lock:
        root.mkdir(parents=True, exist_ok=True)
        with (root / ".config.lock").open("a+b") as stream:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def private_file(path: Path):
    if os.name == "nt":
        # SID lookup does not put a secret on a command line.
        principal = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True
        )
        sid = next(csv.reader([principal.stdout.strip()]))[-1]
        result = subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(F)", "*S-1-5-18:(F)"],
            capture_output=True,
        )
        if result.returncode:
            raise DomainError("SECRET_PERMISSIONS_FAILED", "无法限制本地密钥文件权限", 500)
    else:
        path.chmod(0o600)


class Configuration:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / "secrets.json"
        self.saved = (
            loads(self.path.read_bytes()) if self.path.exists() else {"revision": 1, "values": {}}
        )
        self.runtime = self.effective(self.saved["values"])
        self.runtime_revision = self.saved["revision"]
        try:
            checked = loads((self.root / 'connection-status.json').read_bytes())
            if checked.get('identity') == self.connection_identity():
                self.connection = checked['result']
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def connection_identity(self):
        return digest({key:self.runtime.get(key) for key in ('dashscope_base_url','dashscope_api_key')})

    def record_connection(self, result):
        document = {'identity':self.connection_identity(), 'result':result}
        with config_lock(self.root):
            descriptor, name = tempfile.mkstemp(prefix='.connection-', dir=self.root)
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, 'wb') as stream:
                    private_file(temporary)
                    stream.write(canonical(document));stream.flush();os.fsync(stream.fileno())
                os.replace(temporary, self.root/'connection-status.json')
                self.connection = result
            finally:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def effective(saved: dict) -> dict:
        result = dict(saved)
        # dotenv is read-only input; process environment wins over persisted settings.
        from dotenv import dotenv_values

        from .paths import dotenv_file
        dotenv = dotenv_values(dotenv_file())
        for name in EDITABLE:
            environment = os.environ.get(name.upper(), dotenv.get(name.upper()))
            if environment:
                result[name] = environment
        return result

    @staticmethod
    def validate(values: dict):
        if not isinstance(values, dict) or set(values) - EDITABLE:
            raise DomainError("UNKNOWN_CONFIG_FIELD", "配置中存在不允许的字段", 422)
        for key, value in values.items():
            if not isinstance(value, str) or any(ch in value for ch in "\r\n\0"):
                raise DomainError("INVALID_CONFIG", "配置必须为单行文本", 422, field=key)
        endpoint = values.get("dashscope_base_url", "")
        if endpoint:
            url = urlsplit(endpoint)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or not url.path.rstrip("/").endswith("/compatible-mode/v1")
            ):
                raise DomainError(
                    "INVALID_PROVIDER_URL",
                    "请输入HTTPS兼容接口地址，结尾为/compatible-mode/v1",
                    422,
                )
        email = values.get("unpaywall_email", "")
        if "literature_papers_per_property" in values:
            from .retrieval_preferences import papers_value
            papers_value(values["literature_papers_per_property"])
        if values.get('retrieval_policy_version', 'retrieval-release/1') not in {'retrieval-release/1', 'retrieval-feedback/1'}:
            raise DomainError('LITERATURE_RELEASE_INVALID', '检索策略版本无效', 422)
        if values.get('research_delivery_version') not in {None, 'research-delivery/1'}:
            raise DomainError('RESEARCH_DELIVERY_RELEASE_INVALID', '科研交付版本无效', 422)
        if values.get("ads_sort", "score desc") not in {"score desc", "date desc", "citation_count desc", "read_count desc"}:
            raise DomainError("ADS_SORT_INVALID", "ADS排序须为支持的四种顺序", 422)
        if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise DomainError("INVALID_EMAIL", "Unpaywall邮箱格式无效", 422)

    def candidate(self, patch, expected_revision):
        if type(expected_revision) is not int or expected_revision < 1:
            raise DomainError('INVALID_CONFIG_REVISION', '配置修订号须为正整数', 422)
        current = loads(self.path.read_bytes()) if self.path.exists() else {'revision': 1, 'values': {}}
        if current['revision'] != expected_revision:
            raise DomainError('CONFIG_CHANGED', '配置已更新，请刷新')
        self.validate(patch)
        result = dict(current['values'])
        result.update({k: v for k, v in patch.items() if k not in SECRET_FIELDS or v})
        self.validate(result)
        return result

    def activate(self):
        # Replace the mapping; in-flight model calls retain their existing snapshot.
        self.runtime = self.effective(self.saved['values'])
        self.runtime_revision = self.saved['revision']

    def save(self, patch: dict, expected_revision: int) -> dict:
        if type(expected_revision) is not int or expected_revision < 1:
            raise DomainError("INVALID_CONFIG_REVISION", "配置修订号须为正整数", 422)
        with config_lock(self.root):
            self.saved = (
                loads(self.path.read_bytes())
                if self.path.exists()
                else {"revision": 1, "values": {}}
            )
            self._save_locked(patch, expected_revision)
        return self.public()

    def _save_locked(self, patch: dict, expected_revision: int):
        if expected_revision != self.saved["revision"]:
            raise DomainError("CONFIG_CHANGED", "配置已更新，请刷新")
        self.validate(patch)
        updated = dict(self.saved["values"])
        for key, value in patch.items():
            if key not in SECRET_FIELDS or value:
                updated[key] = value
        self.validate(updated)
        document = {"revision": self.saved["revision"] + 1, "values": updated}
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".config-", dir=self.root)
        path = Path(temporary)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                private_file(path)
                stream.write(canonical(document))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(path, self.path)
            self.saved = document
        finally:
            path.unlink(missing_ok=True)

    def import_csv(self, path: Path) -> dict:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream))
        fields = {row[0]: row[1] for row in rows if len(row) >= 2}
        key = fields.get("apiKey")
        endpoint = fields.get("openAiCompatible")
        if not key or not endpoint or rows and {"apiKey", "openAiCompatible"} <= set(rows[0]):
            # Also accept an ordinary header-row export.
            records = list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))
            if len(records) == 1:
                key, endpoint = records[0].get("apiKey"), records[0].get("openAiCompatible")
        if not key or not endpoint:
            raise DomainError("INVALID_CREDENTIAL_EXPORT", "CSV中缺少密钥或兼容接口地址", 422)
        return self.save(
            {"dashscope_api_key": key, "dashscope_base_url": endpoint}, self.saved["revision"]
        )

    def public(self):
        saved_effective = self.effective(self.saved["values"])
        configured = {key: bool(saved_effective.get(key)) for key in REQUIRED_CONNECTION_FIELDS}
        runtime_configured = {key: bool(self.runtime.get(key)) for key in REQUIRED_CONNECTION_FIELDS}
        return {
            "saved_revision": self.saved["revision"],
            "runtime_revision": self.runtime_revision,
            "effective_values": {"ads_sort": self.runtime.get("ads_sort", "score desc"),
                "literature_papers_per_property": self.runtime.get("literature_papers_per_property", "20")},
            "configured": configured,
            "runtime_configured": runtime_configured,
            "setup_complete": all(runtime_configured.values()),
            "restart_required": saved_effective != self.runtime,
            "env_overrides": sorted(key for key in EDITABLE if os.environ.get(key.upper())),
            "editable_values": {
                key: self.saved["values"].get(key, "") for key in EDITABLE - SECRET_FIELDS
            },
            "models": MODELS,
            "connection": getattr(self, 'connection', {'state': 'configured' if all(self.runtime.get(k) for k in ('dashscope_api_key','dashscope_base_url')) else 'missing'}),
            "profile_readiness": "not_validated",
        }
