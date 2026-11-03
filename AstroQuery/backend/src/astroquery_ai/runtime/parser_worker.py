"""Disposable memory-limited parser process. This module never opens a URL."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
from pathlib import Path


def limit_memory(byte_limit=512 * 1024**2):
    if os.name != "nt":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (byte_limit, byte_limit))
        return None
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_longlong),
            ("job_time", ctypes.c_longlong),
            ("flags", wintypes.DWORD),
            ("min_working", ctypes.c_size_t),
            ("max_working", ctypes.c_size_t),
            ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class IOCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_ulonglong)
            for name in (
                "read_ops",
                "write_ops",
                "other_ops",
                "read_bytes",
                "write_bytes",
                "other_bytes",
            )
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", BasicLimits),
            ("io", IOCounters),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t),
            ("peak_job_memory", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    handle = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.basic.flags = 0x100 | 0x2000
    limits.process_memory = byte_limit
    if (
        not handle
        or not kernel.SetInformationJobObject(
            handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        )
        or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess())
    ):
        raise RuntimeError("PARSER_ISOLATION_UNAVAILABLE")
    return handle  # retained until process exit


def main():
    for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[variable] = '1'
    _memory_handle = limit_memory()
    request = json.loads(sys.stdin.buffer.read(512 * 1024 + 1))
    from astroquery_ai.science.documents import inspect_pdf, page_image

    if request["operation"] == "probe_pdf":
        from astroquery_ai.science.documents import probe_pdf
        result = probe_pdf(Path(request['path']))
    elif request["operation"] == "inspect_pdf":
        result = inspect_pdf(Path(request["path"]))
    elif request["operation"] == "figure_candidates":
        from astroquery_ai.science.papers.figures import inspect_figure_pages
        result = inspect_figure_pages(Path(request["path"]), pages=request.get('pages'))
    elif request["operation"] == "figure_crop":
        from astroquery_ai.science.papers.figures import crop_page
        result = {"png": base64.b64encode(crop_page(Path(request["path"]), request["page"],
                  request["bbox"], dpi=request.get("dpi", 150))).decode("ascii")}
    elif request["operation"] == "page_image":
        result = {
            "png": base64.b64encode(
                page_image(Path(request["path"]), request["page"], dpi=request.get("dpi", 150),
                           display_only=request.get("display_only") is True)
            ).decode("ascii")
        }
    elif request["operation"] == "structured_archive":
        from astroquery_ai.science.archives import structured_archive

        result = structured_archive(
            Path(request["path"]), original_filename=request["original_filename"]
        )
    elif request["operation"] == "structured_table":
        from astroquery_ai.science.attachments import structured_table

        result = structured_table(
            Path(request["path"]),
            request["format"],
            request["table_id"],
            **{
                key: value
                for key, value in request.items()
                if key
                in {
                    "header_only",
                    "id_column",
                    "namespace",
                    "aliases",
                    "candidate_patterns",
                    "maximum_rows",
                    "readme_text",
                    "original_filename",
                }
            },
        )
    else:
        raise ValueError("unsupported parser operation")
    sys.stdout.buffer.write(
        json.dumps({"ok": True, "result": result}, ensure_ascii=False, allow_nan=False).encode(
            "utf-8"
        )
    )


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        # Do not print source text, file paths or exception bodies.
        sys.stdout.buffer.write(
            json.dumps(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "code": getattr(exc, "code", "PARSER_FAILED"),
                }
            ).encode()
        )
        raise SystemExit(1)
