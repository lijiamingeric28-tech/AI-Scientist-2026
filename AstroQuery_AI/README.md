# AstroQuery Final

天文科学数据查找、解析与整合 AI 应用（赛题方向 1）。

## 系统架构

```
astroquery-ai ──► 意图澄清 (Node1)
    │         └─ 保留用户原文，不翻译性质
    ▼
P1 性质标准化 ◄── SIMBAD 解析 + RAG 性质库（rag_properties/）
    │         └─ LLM 按 otype 选性质 → PropertySpec（字段名白名单 + 标准单位表）
    ▼
检索 (子图2)
    ├─ 数据库：27 星表 VizieR 查询，列名经 LLM 归一到 PropertySpec
    ├─ 论文：ADS 搜索（用 RAG 标准名构造查询串）→ Unpaywall → PDF 瀑布式下载
    └─ 补充材料：CDS J/ 表，列名同样归一到 PropertySpec
    ▼
提取 (子图3)
    └─ VLM 提取：prompt 注入 PropertySpec 白名单，field_name 强约束
    ▼
聚合 (aggregator)
    └─ final_output（含 research_domain / simbad_info / error_log）
    ▼
质量管线 (quality_pipeline) ◄── 接缝适配器注入 target_schema + standard_units
    └─ Assessment → Normalization/Conflict → Export → Insights
```

## 目录结构

```
astroquery_final/
├── astroquery_ai/            # 上游主图装配：澄清 + 检索 + 提取 + quality 接缝
│   ├── config.py             #   唯一配置模块（pydantic-settings，env 优先）
│   ├── logger.py             #   统一日志工厂
│   ├── schemas/              #   State 契约层（子图 IO Pydantic schema）
│   ├── cli.py                #   命令行入口
│   ├── property_standardization.py  # P1 性质标准化（系统中枢）
│   ├── quality_adapter.py           # 接缝适配器
│   └── main_graph.py                # 主图装配
├── quality_pipeline/         # 质量管线主图 + 共享设施（configs/models/tools/utils）
├── subgraphs/                # 9 个子图（subgraph1/2/3 + data_assessment/normalization/conflict/export/insights/human_review）
├── rag_properties/           # RAG 性质库（~100 个 otype，含标准单位）
├── web/                      # FastAPI 后端（任务管理/SSE 实时事件/回放）+ sqlite
├── frontend/                 # React + Vite 前端（7 阶段卡片、溯源查看、质量报告）
├── scripts/                  # 工具脚本（KB 覆盖率、P18 对照实验等）
├── tests/                    # pytest 测试（全 mock 离线）
├── docs/                     # 申报技术报告 / FRONTEND_INTEGRATION / shots
└── .env                      # API Keys（ADS/Unpaywall/阿里云百炼 Qwen）
```

## 运行

```bash
# 安装后（推荐）：终端命令
pip install -e .
astroquery-ai "M31 的距离和金属丰度"

# 未安装时：模块方式
python -m astroquery_ai "M31 的距离和金属丰度"

# 或交互模式
python -m astroquery_ai

# Web 应用（前端需先 npm run build 到 frontend/dist）
python -m web.main        # http://127.0.0.1:8000
```

## 测试与门禁

```bash
python -m pytest tests/ -m "not network"   # 全 mock 离线
python -m pytest tests/                    # 含网络冒烟（需真实 API Keys）
python -m ruff check .                     # 全库 lint
```

依赖：`pip install -e .`（pyproject.toml 已声明全部运行时依赖，含 Web 层 fastapi/uvicorn/sse-starlette/langgraph-checkpoint-sqlite；vcrpy 在 dev extra）

## 关键实验开关（P18 消融对照，默认关闭不影响线上行为）

- `QUALITY_PIPELINE_ENABLED`（质量管线开关）、`PAPER_CHAIN_ENABLED`（论文检索链）、`CATALOG_WHITELIST`（星表白名单）、`P1_SPEC_OVERRIDE`（固定 P1 性质集）——详见 `docs/申报技术报告.md` P18

## 知识库

- `quality_pipeline/data/insight_knowledge/astrophysics/` 294 条（7 文件，hypothetical_queries 100% 覆盖）

## 关键设计

- **PropertySpec 是系统中枢**：字段名白名单 + 标准单位表，三条提取路径（数据库/论文/补充材料）全部归一到它
- **向上游对齐**：SIMBAD（实体/otype）+ RAG（性质/单位）是权威源，下游推断机制降级为兜底
- **原始单位保留**：上游不换算，下游 unit_converter 留痕（original_unit → final_unit），满足赛题"单位不一致修正"可追溯要求
- **LLM 列名映射**：VizieR 列名 → PropertySpec，按 (表, 性质指纹) 缓存，异步并发
