# AstroQuery

用自然语言查询天体性质，从星表、论文和官方附表取得测量，在同一份结果中查看原报、独立误差、测量条件和来源。每次查询有自己的交付修订，历史问答和处理过程可以回放。

## 在本机运行

使用 Python 3.12 或 3.13，以及 Node.js 22.12 以上版本。从本目录执行下列命令。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
cd frontend
npm ci
npm run build
cd ..
python -m uvicorn astroquery_ai.api.http:create_app --factory --host 127.0.0.1 --port 8781
```

打开 [AstroQuery](http://127.0.0.1:8781/)。macOS 和 Linux 使用 `source .venv/bin/activate` 激活环境。开发前端时，在另一个终端进入 `frontend` 运行 `npm run dev`，开发服务器会把 API 请求转给本机 8781 端口。

**体验现有结果**　在左侧选择「演示样例」。建议从首位的 **SN 2014J** 开始，在成果页打开 Na I D 等值宽度 **5.8 Å**，沿原始证据追到论文第 5 页。回放会重现当时的问题和答案，点击锁定的原答只推进播放。六例的测量、来源、图注、审核及阶段事件随项目提供，查看这些内容不需要密钥。论文 PDF 按需从公开来源取得，核对文件哈希后才用于显示原页和研究图像。来源无法提供同一版本时仍可查看原报、摘录和出处。

**开始自己的查询**　在「设置 → 服务连接」填写百炼的兼容接口地址和 API Key、ADS Token 及 Unpaywall 联系邮箱。连接就绪后，产品安装随包提供的 100 类性质库、对应知识库和软件资格记录。「使用偏好」可以调整 ADS 排序和每项性质的论文目标。已有查询沿用创建时的选择。

开发安装默认将个人数据写入本目录的 `runtime-data/`。通过环境变量 `ASTROQUERY_DATA_ROOT` 可以显式指向已有数据目录。密钥由本机的服务连接设置管理。对于安装好的 wheel，默认使用当前用户的应用数据目录。

## 演示目录

| 案例 | 推荐看点 | 记录 / 来源 / 图像 |
|---|---|---:|
| **SN 2014J · 首选演示** | 峰值星等、色余和星际吸收线。从原页核对测量，再看红化的人工判断 | 154 / 35 / 55 |
| HD 209458 b | 比较不同研究给出的行星质量、半径和轨道倾角 | 46 / 35 / 27 |
| 织女星 | 对照论文拟合表，查看 9547 ± 17 K 的主值和统计误差 | 64 / 23 / 38 |
| PSR J0437−4715 | 从轨道周期找到 VizieR 原始行、目标名和误差列 | 35 / 55 / 19 |
| M45 昴星团 | 比较星团测距方法，区分统计误差和系统误差 | 45 / 23 / 37 |
| 大角星 | 浏览四项恒星大气性质、跨文献条件和多次审核 | 337 / 39 / 83 |

样例按真实修订发布。SN 2014J 的峰值视星等中保留了个别误归的绝对星等，M45 和脉冲星各有已知的错对象记录。回放及任务评分反映处理经过，选用单条测量时可查看作者原报。完整研究文件取决于原站的可用性。

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
| 演示样例 | `frontend/public/demo-catalog.json` 决定顺序和首选。六份固定历史在 `resources/demos/`，首次打开时按任务读取。个人查询与样例在侧栏分开展示 |

表中后端简称目录均位于 `backend/src/astroquery_ai/`。完整审定包和公开部署使用同一个科学规则编译器。发布工具先核对完整输入，再打包运行所需记录。启动时重新生成消费视图并与固定版本核对。资格记录仍独立校验，运行时不依赖旧版目录。

维护者可用 `python -m astroquery_ai.tools.pack_reviewed_registry --help` 和 `python -m astroquery_ai.tools.pack_demos --help` 重建发布数据。前者需要完整审定包和指定版本的哈希，后者需要本机已结束的真实查询和明确选择的交付修订。公开样例包含科研和回放所需的事实。账户设置、计费账本、模型调用原文和整库的下载缓存留在产生查询的机器上。

## 验证和构建

```powershell
python -m pytest
cd frontend
npm test
npm run build
cd ..
python -m pip wheel --no-deps --wheel-dir .build/wheels .
```

前端构建输出位于 `frontend/dist/`，安装包会收录该界面。Windows 桌面构建从装有 `.[build]` 依赖的源码环境运行 `python -m astroquery_ai.tools.build_product --windows`。单独的 Windows 运行依赖锁见 `requirements-windows.lock`。
