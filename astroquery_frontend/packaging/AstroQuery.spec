# -*- mode: python ; coding: utf-8 -*-
"""AstroQuery 绿色免安装包 PyInstaller spec（onedir 模式）

构建：
    build_venv/Scripts/pyinstaller packaging/AstroQuery.spec --clean -y

产物：dist/AstroQuery/
    AstroQuery.exe        入口（启动服务 + 开浏览器）
    _internal/            运行时（Python + 依赖 + 前端静态资源 + 数据文件）
    data/                 首次运行自动生成（output/web/papers/.env）
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

_PROJECT_ROOT = os.path.dirname(SPECPATH)  # spec 在 packaging/ 下，上级即项目根

datas, binaries, hiddenimports = [], [], []

# 数据文件（保持相对包根结构，打包后落在 _internal 对应路径，代码内 __file__ 定位依旧成立）
# 子图/质量管线的数据文件目录（collect_data_files 对子包不生效，显式整目录拷贝）
datas += [(os.path.join(_PROJECT_ROOT, "subgraphs", "subgraph2", "catalog"), "subgraphs/subgraph2/catalog")]
datas += [(os.path.join(_PROJECT_ROOT, "quality_pipeline", "configs"), "quality_pipeline/configs")]
datas += [(os.path.join(_PROJECT_ROOT, "quality_pipeline", "data"), "quality_pipeline/data")]
datas += [(os.path.join(_PROJECT_ROOT, "rag_properties"), "rag_properties")]
datas += collect_data_files("astroquery_ai", includes=["*.json"])

# 第三方库的数据/二进制（astroquery 有大量数据表，ads/dashscope/pymupdf 需完整收集）
for pkg in ("astroquery", "ads", "dashscope", "json_repair", "langgraph",
            "langchain_openai", "pymupdf", "fitz", "openai", "sse_starlette"):
    try:
        _d, _b, _h = collect_all(pkg)
        datas += _d; binaries += _b; hiddenimports += _h
    except Exception:
        pass

# 前端静态资源 → 包内 resources/frontend_dist（launcher 读取 ASTROQUERY_FRONTEND_DIR）
datas += [(os.path.join(_PROJECT_ROOT, "frontend", "dist"), "resources/frontend_dist")]

# 显式入口模块（web.main 由 launcher import，但 executor/event_bus 等子模块需显式收集）
hiddenimports += ["web.main", "web.executor", "web.event_bus", "web.task_store",
                  "web.replayer", "web.summary", "events", "web.log_bridge"]
hiddenimports += collect_submodules("quality_pipeline")
hiddenimports += collect_submodules("subgraphs")
hiddenimports += collect_submodules("astroquery_ai")

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[_PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "tests", "vcrpy", "ipython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="AstroQuery",
    console=False,            # 无控制台窗口（GUI 应用）；排障时可改 True
    icon=os.path.join(SPECPATH, "icon.ico"),
    uac_admin=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="AstroQuery",
)
