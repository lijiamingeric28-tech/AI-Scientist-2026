# AstroQuery AI —— PyInstaller 打包 spec（onedir 绿色文件夹）
#
# 构建：  python -m PyInstaller --noconfirm --clean packaging/astroquery_ai.spec
# 产物：  dist/AstroQueryAI/AstroQueryAI.exe （连同 _internal/ 整体即绿色包）
# 发布：  整个 dist/AstroQueryAI/ 压缩 zip → GitHub Release 附件（附件限 2GB/件）
#
# 约定：
#   · 只读资源（frontend/dist、rag_properties、configs、insight 规则、icon）打进 _internal/
#     —— 运行时 web.main.ROOT = sys._MEIPASS 指向该处
#   · 运行态产物（web/data/*、output/）首启自动写在 exe 旁边（可写目录）
#   · 不打包：.env（API Key 外置，放 exe 旁边）、sample_pack/（162MB 演示包，可选外置）、
#     web/data/ 与 output/ 的本地残留
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # AstroQuery_AI/ 根（spec 所在 packaging/ 的上级）
ENTRY = os.path.join(SPECPATH, "launcher_entry.py")

datas = [
    (os.path.join(ROOT, "frontend/dist"), "frontend/dist"),          # 前端静态（892KB）
    (os.path.join(ROOT, "rag_properties"), "rag_properties"),        # 99 类天体 PropertySpec（1.3MB）
    (os.path.join(ROOT, "quality_pipeline/configs"), "quality_pipeline/configs"),  # quality_rules/schema_mapping/… yaml
    (os.path.join(ROOT, "quality_pipeline/data"), "quality_pipeline/data"),        # insight_knowledge 领域规则（496KB）
    # subgraph2 检索子图运行必需配置（2026-09-04：Node 2 打包失败根因——catalog 三件 + 列名映射缓存）
    (os.path.join(ROOT, "subgraphs/subgraph2/catalog/catalog_config.json"), "subgraphs/subgraph2/catalog"),
    (os.path.join(ROOT, "subgraphs/subgraph2/catalog/catalog_metadata.json"), "subgraphs/subgraph2/catalog"),
    (os.path.join(ROOT, "subgraphs/subgraph2/catalog/catalog_units.json"), "subgraphs/subgraph2/catalog"),
    (os.path.join(ROOT, "subgraphs/subgraph2/config/column_mapping_cache.json"), "subgraphs/subgraph2/config"),
    (os.path.join(ROOT, "icon.ico"), "."),                           # 窗口/任务栏图标
]

# astroquery 包数据文件（2026-09-04：import astroquery 即读包根 CITATION，无后缀文件
# 不会被 PyInstaller 自动收集——此前正是 Node 2 失败的真正根因）
datas += collect_data_files("astroquery", excludes=["**/tests/**", "**/__pycache__/**"])

# pyvo 包数据文件（2026-09-04：pyvo.samp.constants import 期经 astropy.get_pkg_data_filename
# 读 samp/data/astropy_icon.png——缺失时 astropy 降级去死链 URL 下载（404→崩溃），
# 见 Node 2 失败第二根因）
datas += collect_data_files("pyvo", excludes=["**/tests/**", "**/__pycache__/**"])

# astropy 包数据（2026-09-04：astropy 8 处 get_pkg_data_filename 运行时读坐标数据/等，
# 官方 hook 只收集了部分——统一收全非测试数据，防同类"缺失→死链下载→崩溃"）
datas += collect_data_files("astropy", excludes=["**/tests/**", "**/__pycache__/**", "**/iers/**"])

hiddenimports = [
    # uvicorn 动态加载的协议/循环/生命周期（PyInstaller 常漏，必须显式）
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.lifespan.auto",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto",
    # pywebview WinForms 后端 + pythonnet（CLR）
    "pywebview.platforms.winforms", "clr",
    # 动态解析的配置模块
    "quality_pipeline.configs.domain_config",
    "langgraph.checkpoint.sqlite",
] + collect_submodules("uvicorn.protocols") + collect_submodules("uvicorn.loops")

# 环境残留大件（项目源码并不 import 它们，排除以瘦身；若运行验证发现缺包再按需补回）
excludes = [
    "torch", "torchvision", "torchao", "transformers", "tokenizers",
    "safetensors", "accelerate", "hf_xet", "triton", "numpy.f2py",
    "cv2", "IPython", "matplotlib", "pandas", "scipy", "pyarrow",
    "polars", "openpyxl", "xlsxwriter", "tensorflow", "jax", "keras",
    "onnx", "onnxruntime", "soundfile", "wave", "grpcio", "zmq",
]

a = Analysis(
    [ENTRY],
    pathex=[ROOT],                     # 保证 web/astroquery_ai/subgraphs/quality_pipeline 绝对导入可解析
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AstroQueryAI",
    icon=os.path.join(ROOT, "icon.ico"),
    console=False,                     # 无黑框；日志走 [icon-debug]/服务日志（调试期可临时 True）
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="AstroQueryAI",               # → dist/AstroQueryAI/
)

# ── 内建演示样例包（2026-09-04）──
# 放到绿色包外层（exe 同级）：双击启动后 import_sample_pack 自动探测 cwd/sample_pack → 导入 17 组演示。
# 不在 _internal（保持包内只读资源目录语义，且用户可直接看到/删除演示包）。
import shutil as _sh

_sample_src = os.path.join(ROOT, "sample_pack")
_sample_dst = os.path.join(ROOT, "dist", "AstroQueryAI", "sample_pack")
if os.path.isdir(_sample_src) and not os.path.isdir(_sample_dst):
    _sh.copytree(_sample_src, _sample_dst)
    print(f"[spec] 内建演示样例包: {_sample_src} → {_sample_dst}")
