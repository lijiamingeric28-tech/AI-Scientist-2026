# AstroQuery 绿色免安装包构建

## 产物形态

```
dist/AstroQuery/
├── AstroQuery.exe         # 双击启动：拉起服务 + 自动打开浏览器
├── _internal/             # Python 运行时 + 依赖 + 前端静态资源 + 数据文件（只读）
└── data/                  # 首次运行自动生成：output/ web/ papers/ .env（可写，可整体备份）
```

## 构建步骤（Windows）

```bash
# 1. 打包 venv（Python 3.12，PyInstaller 对 3.13+ 兼容不佳）
"C:\Users\<user>\AppData\Local\Programs\Python\Python312\python.exe" -m venv build_venv
build_venv\Scripts\pip install -e . pyinstaller

# 2. 构建前端
cd frontend && npm run build && cd ..

# 3. 打包
build_venv\Scripts\pyinstaller packaging\AstroQuery.spec --clean -y --distpath dist --workpath build

# 4. 验证（在无 Python 环境/独立目录运行）
dist\AstroQuery\AstroQuery.exe
```

## 运行约束

- **必须联网**：依赖阿里云百炼 Qwen API、SIMBAD/VizieR/ADS/Unpaywall。
- **首次启动**：`data/.env` 自动生成，填 `DASHSCOPE_API_KEY`（必需）、`ADS_API_TOKEN`、`UNPAYWALL_EMAIL`；
  也可在 Web 界面「设置」页填写（写回 data/.env）。
- **数据目录**：任务产物、论文 PDF、数据库全部落在 `data/`，可整体拷贝/备份/迁移。
- 环境变量覆盖：`ASTROQUERY_DATA_DIR`（数据目录）、`ASTROQUERY_FRONTEND_DIR`（前端资源）、`ASTROQUERY_PORT`（端口，默认 8000）。

## 代码改动（为打包而加，均默认不影响开发环境）

| 文件 | 改动 |
|---|---|
| `web/main.py` | DATA_DIR/OUTPUT_DIR/PAPERS_ROOT/.env/前端目录支持 `ASTROQUERY_DATA_DIR`/`ASTROQUERY_FRONTEND_DIR` 覆盖 |
| `subgraphs/subgraph2/config/__init__.py` | papers 下载目录支持 ASTROQUERY_DATA_DIR 外置 |
| `subgraphs/data_export/agents/export_generation_agent.py` | 导出 output/ 支持 ASTROQUERY_DATA_DIR 外置 |
| `packaging/launcher.py` | exe 入口：环境注入 + 启动服务 + 开浏览器 |
| `packaging/AstroQuery.spec` | PyInstaller 配置（collect_all 第三方 + 数据文件 + 前端资源） |

## 已知边界

- 单查询约 25 分钟、executor 并发 = 1（与源码一致）。
- 打包体积约 300-400MB（Python + numpy + PyMuPDF + langgraph 等）。
- `console=False`：无控制台窗口；排障时改 spec 为 `console=True` 重打。
