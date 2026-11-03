# Two entry executables share one immutable dependency directory. The worker
# retains pipe-capable console streams but is launched with CREATE_NO_WINDOW.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

root = Path(SPECPATH).parents[1]
data = [(str(root / 'resources'), 'astroquery_ai_resources')]
data += collect_data_files('webview')
data += collect_data_files('astropy')
data += collect_data_files('langgraph')
for line in (root / 'requirements-windows.lock').read_text(encoding='utf-8').splitlines():
    if line and not line.startswith('#'):
        data += copy_metadata(line.split('==')[0])
analysis = Analysis([str(root / 'tools/windows_entry.py')], pathex=[str(root / 'backend/src')],
    binaries=collect_dynamic_libs('pymupdf'), datas=data,
    hookspath=[str(root / 'tools/packaging/hooks')],
    hiddenimports=['webview.platforms.winforms', 'webview.platforms.edgechromium', 'clr', 'pythonnet', 'uvicorn.logging', 'uvicorn.loops.asyncio',
        'uvicorn.protocols.http.h11_impl', 'uvicorn.protocols.websockets.websockets_impl', 'uvicorn.lifespan.on'],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'tkinter', 'gi', 'IPython', 'matplotlib', 'pytest', 'pip_audit', 'quality_pipeline', 'subgraphs'], noarchive=False)
pyz = PYZ(analysis.pure)
desktop = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='AstroQuery', console=False)
worker = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='AstroQueryWorker', console=True)
collect = COLLECT(desktop, worker, analysis.binaries, analysis.datas, strip=False, upx=False, name='AstroQueryAI')
