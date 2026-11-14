"""Bounded isolated parsers. Timeout actually terminates the child."""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path

from .codec import canonical, loads
from .errors import DomainError


class Parsers:
    def __init__(self):
        from .stages import EXECUTION_POLICY
        self.semaphore = asyncio.Semaphore(EXECUTION_POLICY['parse'])
        import hashlib
        worker_source = Path(__file__).with_name('parser_worker.py')
        self.worker_sha256 = (hashlib.sha256(worker_source.read_bytes()).hexdigest()
                              if not getattr(sys,'frozen',False) and worker_source.is_file() else None)

    async def run(self, operation: str, path: Path, *, page=None, dpi=150, timeout=90, **options):
        if "display_only" in options and (operation != "page_image" or type(options["display_only"]) is not bool):
            raise DomainError("PARSER_OPTIONS", "原页预览参数仅适用于图像显示")
        if set(options) - {
            "format",
            "table_id",
            "header_only",
            "id_column",
            "namespace",
            "aliases",
            "candidate_patterns",
            "maximum_rows",
            "row_offset",
            "hdu",
            "readme_text",
            "original_filename",
            "bbox",
            "pages",
            "display_only",
        }:
            raise DomainError("PARSER_OPTIONS", "解析参数超出允许范围")
        async with self.semaphore:
            if getattr(sys, "frozen", False):
                worker = Path(sys._MEIPASS) / "AstroQueryWorker.exe"
                if not worker.is_file():
                    worker = Path(sys.executable).parent / "AstroQueryWorker.exe"
                if not worker.is_file():
                    raise DomainError("PARSER_WORKER_MISSING", "启动包的隔离解析程序缺失")
                command = [str(worker), "--parser-worker"]
            else:
                command = [
                    sys.executable,
                    "-X",
                    "utf8",
                    "-m",
                    "astroquery_ai.runtime.parser_worker",
                ]
            environment = os.environ.copy()
            if not getattr(sys,'frozen',False):
                # The parent can have been imported from a source checkout via
                # sys.path while this interpreter is editable-installed elsewhere.
                # The worker must execute this same package, never that older copy.
                package_root = str(Path(__file__).resolve().parents[2])
                environment['PYTHONPATH'] = os.pathsep.join(filter(None,
                    (package_root, environment.get('PYTHONPATH'))))
            environment.update({name: '1' for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')})
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=environment,
                creationflags=0x08000000 if sys.platform == "win32" else 0,
            )
            request = {
                "operation": operation,
                "path": str(path),
                "page": page,
                "dpi": dpi,
                **options,
            }
            try:
                async with asyncio.timeout(timeout):
                    encoded = canonical(request)
                    if len(encoded) > 512 * 1024:
                        raise DomainError("PARSER_REQUEST_LIMIT", "解析请求超过受控范围")
                    process.stdin.write(encoded)
                    await process.stdin.drain()
                    process.stdin.close()
                    chunks, received = [], 0
                    while chunk := await process.stdout.read(65536):
                        received += len(chunk)
                        if received > 80 * 1024**2:
                            raise DomainError("PARSER_OUTPUT_LIMIT", "解析结果超过受控大小")
                        chunks.append(chunk)
                    code = await process.wait()
                try:
                    body = loads(b"".join(chunks))
                except (ValueError, UnicodeError) as exc:
                    raise DomainError('PARSER_FAILED', '隔离解析进程未返回完整结果，原件已保留', process_exit_code=code) from exc
                if not isinstance(body, dict) or body.get('ok') and 'result' not in body:
                    raise DomainError('PARSER_FAILED', '隔离解析响应协议无效，原件已保留', process_exit_code=code)
                if code or not body.get("ok"):
                    raise DomainError(
                        body.get("code", "PARSER_FAILED"), "隔离解析未成功，原件已保留",
                        parser_error_type=body.get('error_type'), process_exit_code=code,
                    )
                if self.worker_sha256 and body.get('worker_sha256') != self.worker_sha256:
                    raise DomainError('PARSER_VERSION_MISMATCH','解析子进程版本与当前服务不一致，请重启服务后重试')
                if operation in {"page_image", "figure_crop"}:
                    return base64.b64decode(body["result"]["png"], validate=True)
                return body["result"]
            except TimeoutError as exc:
                raise DomainError("PARSER_TIMEOUT", "隔离解析已超时并停止") from exc
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
