"""AstroQuery AI 一键打包与发布脚本。

流程：
1. 编译前端（npm run build）并校验产物完整性（HTML/CSS/JS/Help 图文）
2. 清理旧构建缓存
3. 运行 PyInstaller 生成 onedir 绿色目录（dist/AstroQueryAI/）
4. 校验独立应用关键资源与结构（exe, _internal, sample_pack, .env.example）
5. 运行独立应用自检（--check 参数）验证冻结态环境
6. 压缩为发布包 release/AstroQueryAI-win64.zip 并生成 SHA256 校验码
"""
import hashlib
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent  # AstroQuery_AI/
REPO_ROOT = ROOT_DIR.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
DIST_DIR = ROOT_DIR / "dist" / "AstroQueryAI"
SPEC_FILE = ROOT_DIR / "packaging" / "astroquery_ai.spec"
RELEASE_DIR = ROOT_DIR / "release"
RELEASE_ZIP = RELEASE_DIR / "AstroQueryAI-win64.zip"


def log(msg: str) -> None:
    print(f"\n[build_release] {msg}", flush=True)


def run_cmd(cmd: list[str], cwd: Path | None = None) -> None:
    cmd_str = " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd)
    log(f"执行命令: {cmd_str} (cwd: {cwd or Path.cwd()})")
    p = subprocess.run(cmd_str, cwd=cwd, shell=True)
    if p.returncode != 0:
        raise RuntimeError(f"命令执行失败 (code {p.returncode}): {cmd_str}")


def step1_build_frontend() -> None:
    log("=== Step 1/6: 编译前端静态产物 (Vite) ===")
    run_cmd(["npm", "run", "build"], cwd=FRONTEND_DIR)
    dist_html = FRONTEND_DIR / "dist" / "index.html"
    if not dist_html.is_file():
        raise FileNotFoundError(f"前端构建未产出 index.html: {dist_html}")
    help_dir = FRONTEND_DIR / "dist" / "help"
    if not help_dir.is_dir() or not any(help_dir.iterdir()):
        raise FileNotFoundError(f"前端帮助图文未包含在 dist/help: {help_dir}")
    log(f"前端构建成功: {dist_html} 及其静态资源正常")


def step2_clean_previous() -> None:
    log("=== Step 2/6: 清理旧构建缓存 ===")
    build_dir = ROOT_DIR / "build"
    if build_dir.is_dir():
        log(f"清理 build 目录: {build_dir}")
        shutil.rmtree(build_dir, ignore_errors=True)
    if DIST_DIR.is_dir():
        log(f"清理旧 dist 绿色包: {DIST_DIR}")
        shutil.rmtree(DIST_DIR, ignore_errors=True)


def step3_pyinstaller() -> None:
    log("=== Step 3/6: 执行 PyInstaller 绿色包构建 ===")
    python_exe = sys.executable
    cmd = [python_exe, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC_FILE)]
    run_cmd(cmd, cwd=ROOT_DIR)


def step4_verify_package() -> None:
    log("=== Step 4/6: 验证打包产物完整性 ===")
    exe_path = DIST_DIR / "AstroQueryAI.exe"
    if not exe_path.is_file():
        raise FileNotFoundError(f"未找到主程序: {exe_path}")

    required_paths = [
        DIST_DIR / "AstroQueryAI.exe",
        DIST_DIR / "sample_pack" / "catalog.db",
        DIST_DIR / ".env.example",
        DIST_DIR / "_internal" / "frontend" / "dist" / "index.html",
        DIST_DIR / "_internal" / "frontend" / "dist" / "help" / "entry.jpg",
        DIST_DIR / "_internal" / "rag_properties",
        DIST_DIR / "_internal" / "quality_pipeline" / "configs" / "quality_rules.yaml",
        DIST_DIR / "_internal" / "quality_pipeline" / "data" / "insight_knowledge",
        DIST_DIR / "_internal" / "subgraphs" / "subgraph2" / "catalog" / "catalog_config.json",
        DIST_DIR / "_internal" / "icon.ico",
    ]
    for p in required_paths:
        if not p.exists():
            raise FileNotFoundError(f"打包产物缺失必需资源: {p}")
        log(f"  [OK] 资源确认: {p.relative_to(DIST_DIR)}")

    log("执行 exe 自检 (--check 探针)...")
    p = subprocess.run([str(exe_path), "--check"], cwd=DIST_DIR, capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise RuntimeError(f"主程序自检失败 (exit {p.returncode}):\nSTDOUT: {p.stdout}\nSTDERR: {p.stderr}")
    log(f"  [OK] 主程序自检通过 (exit 0): {p.stdout.strip()}")


def step5_create_zip() -> None:
    log("=== Step 5/6: 打包发布压缩文件 ===")
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    if RELEASE_ZIP.is_file():
        RELEASE_ZIP.unlink()

    log(f"正在创建 Zip: {RELEASE_ZIP} ...")
    t0 = time.time()
    with zipfile.ZipFile(RELEASE_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, _, files in os.walk(DIST_DIR):
            for file in files:
                file_path = Path(root) / file
                rel_in_dist = file_path.relative_to(DIST_DIR.parent)  # 保留 AstroQueryAI/... 顶层目录
                zf.write(file_path, str(rel_in_dist))

    duration = time.time() - t0
    size_mb = RELEASE_ZIP.stat().st_size / (1024 * 1024)
    log(f"Zip 打包完成: {RELEASE_ZIP} (大小: {size_mb:.2f} MB, 耗时: {duration:.1f}s)")

    # 同时复制一份到仓库根目录 release/，方便直接访问
    repo_release_dir = REPO_ROOT / "release"
    repo_release_dir.mkdir(parents=True, exist_ok=True)
    repo_release_zip = repo_release_dir / RELEASE_ZIP.name
    shutil.copyfile(RELEASE_ZIP, repo_release_zip)
    log(f"发布包同步到: {repo_release_zip}")


def step6_checksum() -> None:
    log("=== Step 6/6: 计算发布校验码 ===")
    h = hashlib.sha256()
    with open(RELEASE_ZIP, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    sha256_val = h.hexdigest()
    checksum_file = RELEASE_DIR / f"{RELEASE_ZIP.name}.sha256"
    checksum_file.write_text(f"{sha256_val}  {RELEASE_ZIP.name}\n", encoding="utf-8")
    log(f"SHA256: {sha256_val}")
    log(f"校验文件: {checksum_file}")


def main() -> None:
    log("=== 开始 AstroQuery AI 完整发布构建流程 ===")
    t_start = time.time()
    step1_build_frontend()
    step2_clean_previous()
    step3_pyinstaller()
    step4_verify_package()
    step5_create_zip()
    step6_checksum()
    total_time = time.time() - t_start
    log(f"=== 全部打包与发布构建成功！总耗时: {total_time / 60:.1f} 分钟 ===")


if __name__ == "__main__":
    main()
