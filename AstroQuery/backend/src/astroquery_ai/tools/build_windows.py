"""Build from an immutable allowlisted snapshot, never from live user data."""

from __future__ import annotations

import hashlib
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from astroquery_ai.runtime.paths import source_product, build_root, frontend_dist


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    ROOT, OUTPUT = source_product(), build_root()
    if sys.platform != "win32":
        raise SystemExit("Windows builds require a Windows build host")
    build_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stage = (OUTPUT / "windows" / build_id / "snapshot").resolve()
    if not stage.is_relative_to(OUTPUT.resolve()):
        raise SystemExit("build path escapes workspace")
    stage.mkdir(parents=True, exist_ok=False)
    for package in ("astroquery_ai", "web"):
        for source in (ROOT / "backend/src" / package).rglob("*.py"):
            if source.is_symlink() or "__pycache__" in source.parts:
                continue
            target = stage / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    for relative in (
        "tools/windows_entry.py",
        "tools/packaging/windows.spec",
        "tools/packaging/Windows使用说明.txt",
        "requirements-windows.lock",
    ):
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    shutil.copytree(ROOT / "tools/packaging/hooks", stage / "tools/packaging/hooks")
    shutil.copytree(ROOT / "resources", stage / "resources", ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'frontend'))
    resource_package = stage / 'backend/src/astroquery_ai_resources'
    resource_package.mkdir()
    shutil.copy2(ROOT / 'resources/__init__.py', resource_package / '__init__.py')
    shutil.copytree(frontend_dist(), stage / 'resources/frontend')
    content_root = ROOT / "resources/insight_kb"
    if (content_root / "content-manifest.json").is_file():
        raw = (content_root / "content-manifest.json").read_bytes()
        content_manifest = json.loads(raw)
        for relative in ["content-manifest.json", *content_manifest["files"]]:
            source = (content_root / relative).resolve()
            if not source.is_relative_to(content_root.resolve()):
                raise SystemExit("knowledge content path escapes declared root")
            payload = source.read_bytes()
            if (
                relative != "content-manifest.json"
                and hashlib.sha256(payload).hexdigest()
                != content_manifest["files"][relative]["sha256"]
            ):
                raise SystemExit("knowledge content changed during build snapshot")
            target = stage / "resources/insight_kb" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
    manifest = {
        "schema_version": "windows-build/2",
        "build_id": build_id,
        "desktop_executable": "AstroQueryAI.exe",
        "renderer": "Microsoft Edge WebView2",
        "scientific_libraries": "pinned registry, knowledge, qualifications and published demo archives",
        "source_files": {},
    }
    for path in sorted(stage.rglob("*")):
        if path.is_file():
            manifest["source_files"][path.relative_to(stage).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    (stage / "build-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    destination = OUTPUT / "windows" / build_id / "dist"
    destination.mkdir(parents=True)
    log = stage.parent / "pyinstaller.log"
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(destination),
                "--workpath",
                str(stage.parent / "work"),
                str(stage / "tools/packaging/windows.spec"),
            ],
            cwd=stage,
            env={**os.environ, "PYTHONPATH": str(stage / "backend/src")},
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    if result.returncode:
        print(json.dumps({"build_id": build_id, "status": "failed", "log": str(log)}))
        raise SystemExit(result.returncode)
    package = destination / "AstroQueryAI"
    internal = package / "_internal"
    (package / "AstroQueryWorker.exe").replace(internal / "AstroQueryWorker.exe")
    shutil.copy2(stage / "build-manifest.json", internal / "build-manifest.json")
    shutil.copy2(stage / "requirements-windows.lock", internal / "requirements-windows.lock")
    shutil.copy2(stage / "tools/packaging/Windows使用说明.txt", package / "使用说明.txt")
    archive = shutil.make_archive(str(destination / "AstroQueryAI-win64"), "zip", root_dir=destination, base_dir=package.name)
    print(
        json.dumps(
            {
                "build_id": build_id,
                "status": "built_not_yet_verified",
                "path": str(package),
                "archive": archive,
                "log": str(log),
            }
        )
    )


if __name__ == "__main__":
    main()
