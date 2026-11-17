<div align="center">

<img src="assets/readme_title.png" alt="AstroQuery AI" width="100%" />

### 用自然语言问天

**2026 挑战杯 · 阿里云 AI 科研助手 · 科学数据查找、解析与整合**

[![Python](https://img.shields.io/badge/Python-3.12%E2%80%933.13-3776AB?logo=python&logoColor=white)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-编排引擎-10a37f?logo=python&logoColor=white)](https://langchain.com)
[![Qwen-VLM](https://img.shields.io/badge/Qwen--VLM-多模态提取-8b5cf6?logo=openai&logoColor=white)](https://dashscope.aliyun.com)

[![FastAPI](https://img.shields.io/badge/FastAPI-实时后端-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)](https://react.dev)

[![Tests](https://img.shields.io/badge/tests-local%20verification-2ea44f)](#验证和构建)
[![Desktop](https://img.shields.io/badge/桌面内置引擎-WebView2-1f6feb)](#windows-桌面版)
[![Website](https://img.shields.io/badge/🌌-网站落地页-8b5cf6)](https://lijiamingeric28-tech.github.io/AI-Scientist-2026/)

</div>

# AstroQuery AI

从一句自然语言提问出发，在 VizieR 星表、ADS 论文和官方附表中查找测量。每条结果保留作者原报、误差、测量条件和来源。研究者可以回查原件、比较资料、继续追问，并把所选数据和图像导出用于分析。

## Windows 桌面版

下载 Windows x64 压缩包，解压后双击 **AstroQueryAI.exe**。程序会启动本机服务，在自己的 WebView2 窗口中打开，关闭窗口即可退出。[下载 Windows 桌面版](https://github.com/lijiamingeric28-tech/AI-Scientist-2026/releases/latest)

当前源码内置 **10 个真实案例**：SN 2014J 主案例和九个代表性查询。下载链接指向此前发布的程序包；本次只更新源码和案例库，未发布新的 Release 二进制。

可从「演示样例」直接查看已保存的查询。自己的查询和设置保存在程序旁的 `data/` 文件夹，换新版时请保留该文件夹。若系统缺少 WebView2 Runtime，先安装微软提供的 Evergreen x64 运行时。[微软 WebView2 下载页](https://developer.microsoft.com/microsoft-edge/webview2/)

## 从源码运行

使用 Python 3.12 或 3.13，以及 Node.js 22.12 以上版本。从仓库根目录执行下列命令。

```powershell
git clone https://github.com/lijiamingeric28-tech/AI-Scientist-2026.git
cd AI-Scientist-2026
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
cd frontend
npm ci
npm run build
cd ..
python -m uvicorn astroquery_ai.api.http:create_app --factory --host 127.0.0.1 --port 8781
```

浏览器访问 `http://127.0.0.1:8781/`。Windows 也可以在仓库根目录执行 `astroquery-desktop` 打开内置 WebView2 窗口。macOS 和 Linux 使用 `source .venv/bin/activate` 激活环境。开发前端时，在另一个终端进入 `frontend` 运行 `npm run dev`，开发服务器会把 API 请求转给本机 8781 端口。

**体验现有结果**　在左侧选择「演示样例」。首位 **SN 2014J · 多波段光变与红化** 保留 960 条测量、52 幅科研图像和真实科研追问；其余九例覆盖恒星、系外行星、脉动变星、脉冲星、行星状星云、星团、星系、活动星系和星系团。案例的测量、原报、条件、来源、审核、洞察和回放随源码提供，不需要模型密钥即可查看。首次取得未缓存的论文原页或图像需要联网并核对文件哈希；来源不能提供同版原件时仍保留摘录及出处。

**开始自己的查询**　在「设置 → 服务连接」填写百炼的兼容接口地址和 API Key、ADS Token 及 Unpaywall 联系邮箱。连接就绪后，产品安装随包提供的 100 类性质库、对应知识库和软件资格记录。「使用偏好」可以调整 ADS 排序和每项性质的论文目标。已有查询沿用创建时的选择。

从源码运行时，个人数据默认写入根目录的 `runtime-data/`。也可以通过 `ASTROQUERY_DATA_ROOT` 指定已有数据目录。密钥由本机的服务连接设置管理，`.env.example` 列出了可用的环境变量。通过 wheel 安装时，数据默认写入当前用户的应用数据目录。

从旧的子目录结构升级时，如果根目录还没有对应文件，应用会读取旧 `AstroQuery/` 下的 `runtime-data/`、`paths.local.json` 和 `.env`。已有虚拟环境可以重新执行 `python -m pip install -e ".[dev]"`，让安装指向仓库根目录。

## 演示目录

| 案例 | 查询性质 | 测量 / 去重资料 / 图像 |
|---|---|---:|
| SN 2014J · 多波段光变与红化 | 历元波段视星等、视线E(B−V)消光、峰后15日波段衰减、原报极大视星等 | 960 / 40 / 52 |
| HD 209458 · 有效温度与金属丰度 | 有效温度、铁氢丰度比 | 26 / 16 / 5 |
| HD 189733 b · 质量与半径 | 行星半径、行星质量 | 7 / 24 / 19 |
| δ Cep · 脉动周期与色余 | 采用E(B−V)、来源脉动周期 | 30 / 27 / 5 |
| PSR B0531+21 · 自转周期与色散量 | 脉冲星地球至脉冲星视线自由电子柱密度（DM）、源报告恒星自转周期 | 179 / 26 / 11 |
| NGC 7027 · 电子温度与电子密度 | 电子密度、星云电子温度 | 16 / 24 / 5 |
| M67 · 距离与金属丰度 | 星团采用的铁氢丰度比、星团日心距离 | 33 / 24 / 7 |
| 大麦哲伦星系 LMC · 距离与日心径向速度 | 宿主来源采用距离、宿主日心径向速度 | 11 / 25 / 4 |
| NGC 4151 · Hβ 宽线与连续谱光度 | AGN单历元广Hβ半高全宽、AGN 5100Å单色连续谱光度 | 24 / 25 / 10 |
| Abell 1656 · 速度弥散与气体温度 | 星系团静止系视向速度离散、星系团ICM平均kT | 134 / 33 / 11 |

资料按成果页的资料分组去重计数，不等同于来源记录数或独立研究篇数。十例用于展示实际处理流程，不构成全部 100 类天体的正确率验证。局部错提、未决审核和洞察缺口按原任务保留，使用单条测量前应查看原文。PSR B0531+21 的 DM 洞察存在输入容量缺口，且部分候选的 ΔDM/总 DM 范围尚待核对。

## 仓库结构

```text
backend/src/astroquery_ai/  Python 应用与接口
frontend/                   React 工作台与演示目录
resources/                  性质库、知识库、正式样例和桌面资源
tests/                      后端测试
tools/                      打包、维护、自动演示和性能基准
site/                       GitHub Pages 网站
assets/                     网站与 README 共用素材
docs/                       开发与性能文档
```

## 修改入口

| 需要修改的部分 | 从这里开始 |
|---|---|
| HTTP、CLI、桌面启动 | `backend/src/astroquery_ai/api/`。HTTP 在 `http.py` 装配，路由按任务、设置、事件和成果分组 |
| 身份解析、语义澄清和冻结请求 | `query/`。SIMBAD 的目标身份、模型选择的性质候选和用户确认在这里汇合 |
| 星表、论文、附表、图像和引用 | `science/catalog/`、`science/papers/`、`science/workflow/`。原文定位、证据核验和数值表示分别在 `papers/paper_evidence.py`、`papers/evidence_check.py`、`papers/native_values.py` |
| 质检、清洗、数据对照和交付 | `science/unified_quality.py`、`science/processing/`、`science/results/`。业务代码解释材料，正式结果读接口取指定的交付修订 |
| 运行和存储 | `runtime/` 管理作业、持久化、模型和外部访问。`application/` 负责装配以及对话、成果和执行明细的展示投影 |
| 科学库与维护 | `registry/` 负责性质定义、适用范围和审定输入，`science/knowledge.py` 负责知识库。已审核的运行输入在 `resources/`，开发工具在 `backend/src/astroquery_ai/tools/` |
| 对话、记录、图像、执行明细、设置 | `frontend/src/components/` 下的 `chat`、`results`、`workflow`、`settings`。图像查看器和质量分组件在 `results/FigureViewer.jsx` 与 `results/QualityScore.jsx` |
| 演示样例 | `frontend/public/demo-catalog.json` 决定顺序和首选。固定历史在 `resources/demos/`，首次打开时按任务读取。个人查询与样例在侧栏分开展示 |

表中后端简称目录均位于 `backend/src/astroquery_ai/`。完整审定包和公开部署使用同一个科学规则编译器。发布工具先核对完整输入，再打包运行所需记录。启动时重新生成消费视图并与固定版本核对。资格记录仍独立校验，运行时不依赖旧版目录。

维护者可用 `python -m astroquery_ai.tools.pack_reviewed_registry --help` 和 `python -m astroquery_ai.tools.pack_demos --help` 重建发布数据。前者需要完整审定包和指定版本的哈希，后者需要本机已结束的真实查询和明确选择的交付修订。公开样例包含科研和回放所需的事实。账户设置、计费账本、模型调用原文和整库的下载缓存留在产生查询的机器上。

自动演示脚本见 [tools/demo/README.md](tools/demo/README.md)。它驱动应用原生内嵌窗口，复用已保存结果，不录制视频、不重新调用模型。知识与规范工作台均从设置进入，界面跟随系统配色；规范发布只作用于后续使用该版本的新任务。

## 验证和构建

```powershell
python -m pytest
cd frontend
npm test
npm run build
cd ..
python -m pip wheel --no-deps --wheel-dir .build/wheels .
```

前端构建输出位于 `frontend/dist/`，安装包会收录该界面。在 Windows x64 上构建便携版，先安装 `python -m pip install -e ".[build]"` 并在 `frontend/` 执行 `npm ci`，然后从源码目录运行 `python -m astroquery_ai.tools.build_product --windows`。生成的 ZIP 位于 `.build/windows/<构建时间>/dist/`。Windows 运行依赖锁见 `requirements-windows.lock`。
