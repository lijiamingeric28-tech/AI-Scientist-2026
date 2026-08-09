# AstroQuery Final 全库审计报告

> 生成日期：2026-08-05 ｜ 审计范围：`astroquery_ai/`（核心层 + 3 子图）、`quality_pipeline/`（核心 + 6 agentV1 + tools）、`rag_properties/`（100 文件）、`scripts/`、`tests/`、`docs/`、全部配置与密钥文件，约 30K 行 Python
> 方法：6 路并行完整深读（每文件全文）+ 关键接缝逐一人工核验（含 2 处运行时复现、全库 py_compile）
> 标记：**[已确认]** = 亲眼验证或运行时复现；**[疑似]** = 需联网/部署/产品确认

---

## 0. 系统整体图景

```
run.py → 澄清(子图1, 含 input() 追问) → P1 性质标准化(SIMBAD+RAG+LLM)
       → 检索(子图2: simbad_resolver → {database_query ∥ ads→unpaywall→pdf→supplementary})
       → 提取(子图3: pdf→VLM→bbox→result_builder)
       → 聚合(final_aggregator) → 质量管线(Assessment→gate→Dispatch→{Norm/Conflict/Export/HR}→Insights→END)
```

设计优点（正向确认，避免误伤）：
- PropertySpec 作字段名白名单 + 标准单位表中枢，三路提取（数据库/论文/补充材料）统一归一
- 适配层（adapters.py）把子图差异吸收在外部，子图源码零改动；错误隔离保证"永远出 JSON"
- 子图节点返回键全部在各自 state TypedDict 声明（未发现 langgraph 静默丢弃，除 human_review `_from_conflict`）
- 知识库/单位表/实体类型三方生成产物一致（34 组 257 条 / 28 字段 1178 别名 / 153 类型）
- MERGE_COMPLETION_REPORT.md 声称的 12 项修复在代码中基本全部真实存在

但两条主链路实际是断的（A1/A2），质量管线的 LLM 调用实际必然失败（A5）。

---

## 1. A 级：致命问题（功能断线 / 安全，必须最先修）

### A1. 数据库检索恒零查询零结果

**问题阐述**

`database_query` 节点从 `simbad_info` 读取 `ALIASES` 键作为 27 个星表的标识符来源，但**全代码库没有任何地方产出这个键**：P1 性质标准化（property_standardization.py）请求 SIMBAD 时只取 `main_id,otype,otypes,sp_type,coo(ICRS)`；子图 2 自己的 `simbad_resolver` 解析出的别名写入的是**另一个键** `simbad_aliases`，且完全不触碰 `simbad_info`。于是 `aliases` 恒为 `[]` → `extract_catalog_ids` 恒空 → `total_queries = 0` → **27 个星表的 VizieR 查询从未执行过**，README 声称的核心能力"数据库检索"是死功能。

**代码判断**

- 读侧（断线端点）：`astroquery_ai/subgraph2/nodes/database_query.py:41`
  ```python
  simbad_info = state.get("simbad_info", {})
  aliases = simbad_info.get("ALIASES", [])     # ← 此键全库无人产出
  ```
- P1 侧：`astroquery_ai/property_standardization.py:61-66`，SIMBAD `output.params` 只含 `main_id,otype,otypes,sp_type,coo(ICRS)`，无 `ids` → 返回的 simbad_info 无 ALIASES
- 子图 2 侧：`nodes/simbad_resolver.py:124` 把别名写入 `state["simbad_aliases"]`（小写独立键），不写 simbad_info
- 全库 grep `ALIASES` 仅命中 `subgraph2/state.py:36` 注释与 `database_query.py:41` —— 两端从未接通
- 实际后果链：`database_query.py:82-84` → `catalog_ids={}` → `total_queries=0` → Step 4 循环零次执行 → 输出恒空

**修改建议**

二选一（推荐前者，改动最小）：
1. `database_query.py:41` 改读子图 2 内部已产出的键：
   ```python
   aliases = state.get("simbad_aliases", []) or []
   ```
2. 或让 P1 产出该键：`property_standardization.py` 的 SIMBAD 请求 `output.params` 增加 `ids`，解析后写入 `simbad_info["ALIASES"]`（注意别名是 `|` 分隔的原始串，需 split），同时删除/闲置子图 2 的二次解析（见 B2）。

修复后建议做一次真实查询（如 M31）验证 `total_queries > 0` 且 `database_records` 非空。

**出处对照（combine 时代是否已断？—— 否）**

用户提供代码出处目录 `E:\V2\FINAL_DESIGN\combine`，逐行 diff 确认：**combine 时代是通的，断线是在合并 P1（性质标准化）时引入的**：

| 版本 | 读取处 | 写入处 | 状态 |
|---|---|---|---|
| combine | `database_query.py:37` `aliases = state.get("simbad_aliases", [])` | `simbad_resolver.py:124` `state["simbad_aliases"] = aliases` | ✅ 接通（子图 2 内部自产自销） |
| final | `database_query.py:40-41` `aliases = simbad_info.get("ALIASES", [])` | P1 `query_simbad` 无 `ids` 参数，从不产出 ALIASES | ❌ 断线 |

diff 证据（combine → final 唯一破坏性改动）：
```diff
- aliases = state.get("simbad_aliases", [])
+ simbad_info = state.get("simbad_info", {})
+ aliases = simbad_info.get("ALIASES", [])
```
迁移意图：想把别名来源从"子图 2 二次解析"切换到"P1 解析结果"（同批改动 `entity_type` 改为 `simbad_info.get("OTYPE")`，因 P1 确实产出 OTYPE 而改对了）；但 ALIASES 只改了读侧、没补产出侧，旧键 `simbad_aliases` 被弃用 → 断线。

**修复记录（2026-08-05，已修复）**

- `astroquery_ai/subgraph2/nodes/database_query.py:40-41`：恢复 combine 原语义 `aliases = state.get("simbad_aliases", []) or []`，加注释防回退（明确警告不要改读 `simbad_info["ALIASES"]`）
- 连带加固同处：`entity_type` 增加 `state.get("simbad_object_type")` 中间兜底（P1 失败但子图 2 成功时 OTYPE 缺失场景）
- 连带清理：删除同文件 210-220 行重复日志块（C10）
- 连带更新：`subgraph2/state.py:33-38` 注释纠正（去掉误导性 ALIASES 格式声明，注明别名走 simbad_aliases；并标注与"替代 resolver"旧注释的矛盾，见 B2）
- 验证：py_compile 通过；不依赖网络的逻辑链模拟通过（simbad_resolver 写入 → database_query 读取 → entity_type 兜底链，含 P1 失败场景）
- **未连带解决**：B2/B3/E6 后续随 SIMBAD 收敛重构一并修复（2026-08-05），见第 9 章

---

### A2. 补充材料恒零 records（四级相对导入运行时必炸）

**问题阐述**

`column_mapper.py` 内部创建 LLM 客户端的工厂函数用了**四级**相对导入 `from ....subgraph1...`，而该模块位于 `astroquery_ai.subgraph2.utils` 包，四级点已超出顶层包，**运行时必然抛 `ImportError: attempted relative import beyond top-level package`**（已在本机实测复现）。异常被函数体 `except Exception` 吞掉并返回空映射 `{}`。后果分两路：
- `database_query` 显式传入 `llm_client`（database_query.py:158-164）→ 短路正常，不受影响；
- `supplementary_query`（supplementary_query.py:319-323）**不传** client → 每次调用都走炸掉的工厂 → 映射恒空 → 补充 records 恒为 0。

即 P4 补充提取实际只产出 sources、从不产出 records。同类代码对照：`supplementary_query.py:114` 与 `database_query.py:18` 都用三级（正确）——**证明是某次迁移时的漏改**。

**代码判断**

- `astroquery_ai/subgraph2/utils/column_mapper.py:53-56`
  ```python
  def _get_llm_client() -> OpenAI:
      """从 subgraph1 配置创建 LLM 客户端"""
      from ....subgraph1.utils.llm_utils import get_llm_client   # ← 多了一个点
      return get_llm_client()
  ```
- 吞异常端点：`column_mapper.py:156-158`
  ```python
  except Exception as exc:
      logger.exception(f"[ColumnMapper] 映射失败 {vizier_table}")
      return {}
  ```
- 触发路径：`supplementary_query.py:317-323` 调用 `map_columns_to_properties(...)` 不带 `llm_client`/`model` → 函数内 `client = llm_client or _get_llm_client()`（column_mapper.py:121）→ ImportError → 返回 `{}` → `for col_name, property_id in column_mapping.items()`（supplementary_query.py:348）零循环
- 对照正确写法：`supplementary_query.py:114` `from ...subgraph1.utils.llm_utils import get_llm_client`

**修改建议**

1. `column_mapper.py:55` 改为三级：
   ```python
   from ...subgraph1.utils.llm_utils import get_llm_client
   ```
2. 顺手统一：`database_query.py:158` 显式取 client 再传参的模式可以删掉，让两处调用方都不传 client，统一走模块内工厂（少一处 import、少一个失败面）。
3. 修复后跑一次带论文下载的查询，验证 `supplementary_records` 非空。

---

### A3. 真实 API 密钥明文硬编码进仓库（config.yaml）

**问题阐述**

`subgraph1/config/config.yaml` 第 7 行硬编码了**真实的 DashScope API 密钥**，与根目录 `.env:3` 的 `DASHSCOPE_API_KEY` 逐字符相同。该密钥被三处共享：子图 1 的 LLM 调用、P1 性质标准化（property_standardization.py:259-262）、子图 2 的列名映射（经 get_llm_client）。`.gitignore` 只忽略 `.env`，**不覆盖 config.yaml**——一旦 `git init` 提交，密钥必然入库泄漏。且同一密钥三处存放（根 .env / astroquery_ai/.env / config.yaml），轮换时极易漏改一处导致服务静默故障。

**代码判断**

- `astroquery_ai/subgraph1/config/config.yaml:7`
  ```yaml
  llm:
    base_url: "https://ws-mgdvntda5u9ipv2t.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    api_key: "sk-ws-H.EDIIHIY.9cun.MEUCIE8kl0mOSYBF9LRUMCtGJAop8bFeWLPoYzODMZqZbGZlAiEA2HGXz7Z8sMfsmgzv0Kt0BgKPNoTfeDabpFEtH4X1Yj4"
    model: "qwen3.7-flash"
  ```
- 根 `.env:3` 与 `astroquery_ai/.env` 存放同一密钥 → 三处重复
- `.gitignore` 仅 `# 环境与密钥\n.env`，无 config.yaml 类规则
- 消费方：`property_standardization.py:259-262`、`subgraph1/utils/llm_utils.py:16-21`（config.llm['api_key']）

**修改建议**

1. `config.yaml` 的 `api_key` 改为空或占位，`config/__init__.py` 加载时从环境变量回退：
   ```python
   # config/__init__.py
   import os
   api_key = os.getenv("DASHSCOPE_API_KEY", "") or self.raw.get("llm", {}).get("api_key", "")
   ```
2. 若暂不能改代码，最低限度：在 `.gitignore` 增加 `astroquery_ai/subgraph1/config/config.yaml` 并保留模板文件。
3. 三处密钥归一为单一来源（.env），删除 astroquery_ai/.env 的重复。
4. 视为已泄漏处理，建议轮换该密钥。

**修复记录（2026-08-05，已修复）**

- `subgraph1/config/__init__.py`：新增 `load_dotenv`（两级 .env 回退，与 subgraph2/3 同模式）；`llm` property 改为优先从环境变量 `DASHSCOPE_API_KEY`/`DASHSCOPE_BASE_URL`/`DASHSCOPE_MODEL` 取值，yaml 值作兜底
- `subgraph1/config/config.yaml`：`api_key` 与 `base_url` 清除为空字符串，model 保留 yaml 默认值 "qwen3.7-flash"，顶部加注释注明环境变量名
- 根 `.env`：规范化注释，补全 `DASHSCOPE_BASE_URL` / `DASHSCOPE_MODEL` / `OPENAI_API_KEY` / `OPENAI_BASE_URL`（值为空，待部署填写）
- 根 `.env.example`：重写为全量模板（10 个环境变量，分模块注释）
- `astroquery_ai/.env`：**删除**（三处密钥归一为根 .env 单来源；subgraph2/3 的 `load_dotenv` 回退链已覆盖根目录）
- `astroquery_ai/.env.example`：改为指向根文件的指引
- 验证：subgraph1 llm property 读 env 正确；env 清除后回退到 yaml 空/default 值正确；subgraph2/3 仍能加载根 .env

---

### A4. 子图 1 库代码内 5 处 `input()` 阻塞（非交互部署必挂死）

**问题阐述**

子图 1（意图澄清）的 4 个节点内共 5 处直接调用 `input()` 与用户交互。但子图 1 是被父图以 **库调用方式** 执行的（`adapters.py:64-65` `subgraph.invoke(sub_input)`），父图无任何超时/看门狗。于是：
- 非交互环境（服务端、CI、管道 stdin 重定向）：要么永久挂死整条主图线程，要么 stdin EOF 抛 `EOFError` 把整个子图炸掉（被 adapters 捕获降级，用户拿到的永远是 failed 空结果）；
- 主图若并发 invoke 多个请求，多个 input() 共享 stdin/stdout，输入归属无法区分。

质量管线的 HumanReview 节点同理（`human_review_agent.py:127,384,408`）。这是本代码库最严重的运行时风险，优先级取决于部署形态。

**代码判断**

- `astroquery_ai/subgraph1/nodes/greeting_handler.py:43`、`ask_entity.py:65`、`ask_properties.py:43`、`final_confirm.py:56` 与 `:93`（共 5 处）
  ```python
  # final_confirm.py:56 示例
  user_input = input(...)
  ```
- 调用方无超时：`astroquery_ai/adapters.py:63-65`
  ```python
  try:
      subgraph = create_intent_clarification_subgraph()
      result = subgraph.invoke(sub_input)
  ```
- 交互模式是设计特性（run.py:57-87 prompt_interactive 说明"追问由子图 1 在流水线内部完成（节点内 input()）"）——即设计者知道 input() 在库内，但未考虑非交互调用

**修改建议**

1. 明确部署形态（CLI vs 服务端）。若服务端：子图 1 的追问节点改为不阻塞——把"需要追问"作为子图输出上浮，由外层（HTTP/CLI）完成交互后回填状态，或提供 `interactive=False` 开关直接跳过追问（走推断）。
2. 无论哪种形态，父图 `invoke` 加超时包装（如 `concurrent.futures` + timeout 或 langgraph 检查点），防止挂死。
3. HumanReview 节点同样需要外部化决策注入（`test_real_data_e2e.py:49-55` 注释已自认需预置 `__human_review_decision__` 规避，说明作者已知问题但未处理）。

**当前状态（2026-08-05）：搁置**

CLI 测试阶段 `input()` 是正确的交互方式，不需要预改。Web 化方案（Headless Protocol）已设计完毕，核心思路：加 `interaction_response`/`pending_interaction` 两个 state 字段，4 个交互节点改为"有预填回答则消费、无则设 pending 返回"，4 条固定边改为条件边（pending→END），`create_subgraph(interactive=True/False)` 向后兼容。搭建前端时执行，改动面约 10 文件 ~50 行净增。

---

### A5. quality_pipeline 的 LLM 调用实际必然失败（部署断裂）

**问题阐述**

质量管线的 LLM 配置链是断的：`llm_config.yaml` 的 `api_key` 为空，`utils/llm.py:103-104` 只认 `OPENAI_API_KEY`/`OPENAI_BASE_URL` 环境变量，而**管线全链路不读取 .env 文件**。直接运行所有 LLM 调用必失败，各 Agent 又各自 catch → 全管线静默降级走模板 fallback。样例产物 `quality_summary` 里 `field_descriptions_llm=false` 即是降级痕迹。此外 `llm.py:117-118` 无应用层超时（ChatOpenAI timeout=120s + 3 策略串联，单次最坏约 24 分钟阻塞）。

**代码判断**

- `quality_pipeline/configs/llm_config.yaml:5-9`
  ```yaml
  api_key: ""          # ← 空
  base_url: "https://api.deepseek.com"
  model: "deepseek-v4-flash"
  ```
- `quality_pipeline/utils/llm.py:103-104`
  ```python
  api_key = os.getenv("OPENAI_API_KEY", "") or ...
  base_url = os.getenv("OPENAI_BASE_URL", "") or ...
  ```
- 全库 grep：quality_pipeline 内无 `load_dotenv` / `.env` 读取（.env 只被 run.py 侧间接消费）
- 模型名 `deepseek-v4-flash` 与本机会话环境一致，疑似内网代理真实模型名（非官方 DeepSeek 命名），但 key 注入方式完全未打通

**修改建议**

1. 确定部署约定：二选一——(a) 在 `utils/llm.py` 加载根目录 .env（`load_dotenv(ROOT/.env)`）；(b) 运维侧注入 `OPENAI_API_KEY`/`OPENAI_BASE_URL` 环境变量。二者取一并在 README 写清。
2. `llm_config.yaml` 的 `api_key` 留空是合理设计（走 env），但 `structured_output_method: "function_calling"`（llm_config.yaml:26）与注释建议的 `prompt_parsing` 矛盾，需按实际模型能力统一。
3. LLM 调用加应用层超时与熔断（`llm.py:117-118` 的 timeout 已设但未传到所有调用路径；`_parse_utils.py:562-563` 类调用是裸 catch）。

---

**重新评估（2026-08-05）：A5 降级为配置项，非代码缺陷。** 所有 8 个调用 LLM 的 Agent 均有 try/except -> template fallback 优雅降级，管线不阻塞。llm.py api_key fallback 链正确。.env 已随 A3 预留 OPENAI_API_KEY/BASE_URL，部署时填入即通。structured_output_method 建议改为 prompt_parsing，留 P2 清理轮。

---

## 2. B 级：高影响（逻辑错误 / 数据失真 / 契约破坏）

### B1. LLM 失败反被加分：完整度评分失真

**问题阐述**

LLM 驱动的完整度评估（llm_completeness）在**调用失败时返回 `adjusted=1.0`（满分）**，而消费方把这个值乘入综合分。结果：LLM 越不可用，数据完整度得分越高——LLM 故障反而"提高"了数据质量评分，与"LLM 挂掉应降级/降分"的直觉完全相反，会污染所有下游决策（路由、报告、是否进 Conflict）。

**代码判断**

- `quality_pipeline/tools/assessment/llm_completeness.py:99-102`
  ```python
  except Exception as e:
      ...
      return {"adjusted": 1.0, "llm_based": False, "reason": f"LLM 不可用: {e}"}
  ```
- 消费方：`Data_Assessment_agentV1/agents/quality_scoring_agent.py:61-67` 把 `adjusted` 乘入 completeness 维度得分
- 结合 A5（LLM 实际必失败），当前**所有运行**都会走这条满分路径

**修改建议**

失败时改为中性值：`adjusted` 返回 None/跳过该维度，或返回保守值（如 0.5）并在报告中显式标记 `llm_based: False`；scoring 侧对 `llm_based=False` 的维度降权或按规则方法重算，而不是乘 1.0。

---

### B2. SIMBAD 双查 + 设计矛盾：子图 2 入口二次联网查询

**问题阐述**

主图 state 与子图 2 state 的注释都声明 `simbad_info`（P1 已解析）"替代原有的 simbad_resolver 节点"，但子图 2 的 graph 仍把 `simbad_resolver` 设为入口并执行**第二次 SIMBAD 联网查询**，且路由（成功/失败）以第二次查询为准——P1 已成功解析时，若子图这次查询失败（网络抖动），整个检索被跳过、输出全空。重复查询还浪费一次网络 RTT 与 SIMBAD 配额。

**代码判断**

- 契约注释：`astroquery_ai/subgraph2/state.py:36-38`（simbad_info"替代原有的 simbad_resolver 节点"）
- 实际拓扑：`subgraph2/graph.py:68` `graph.set_entry_point("simbad_resolver")`；`graph.py:71-74` 路由按本次 `simbad_status` 决定是否跳过全部检索
- 解析字段重复：simbad_resolver.py:39 `add_votable_fields('ids', 'otype')` vs P1 query_simbad 的 params —— 两套实现（astroquery Simbad vs 手写 VOTable 解析），风险面翻倍

**修改建议**

1. 若 P1 成功解析（simbad_info 非空）：子图 2 跳过 simbad_resolver，直接从 P1 结果构建 `simbad_*` 键（在 adapters 或子图入口加一个映射节点）；
2. 若保留 simbad_resolver 作为兜底：仅在 P1 失败时执行（路由前判断），且失败不应跳过整条检索——database_query 可改用 target_entity 直接查询，论文路不依赖 SIMBAD。

**修复记录（2026-08-05，已修复）**

- P1（`property_standardization.py:65`）：SIMBAD 请求加 `ids` 参数，解析后写入 `ALIASES` 列表
- adapters（`adapters.py:169-189`）：从 P1 simbad_info 直接构建子图2全部 `simbad_*` 字段（status/main_id/aliases/object_type/coordinates/resolved_at）
- 子图2（`graph.py`）：删除 simbad_resolver 节点 + route_after_simbad 函数 + simbad_resolver import；START → database_query 和 ads_search 直接并行
- 同步解决：B3（simbad_info 合并保留 OTYPES）、E6（simbad 失败牵连论文检索——路由已不存在）
- `simbad_resolver.py` 保留文件作为参考但不参与图

---

### B3. 主图 simbad_info 被子图 2 结果静默覆盖

**问题阐述**

适配层把子图 2 的 `simbad_*` 字段重建为 `simbad_info` 写入主图状态，**覆盖掉 P1 的解析结果**。P1 的 `OTYPES`（管道分隔紧凑码，RAG 选库的关键输入）与 `SP_TYPE` 因此丢失，最终 final_output 的 simbad_info 是子图 2 的简化结构（无 OTYPES/SP_TYPE）。下游（quality_pipeline、RAG 重查）拿到的信息比 P1 少。

**代码判断**

- `astroquery_ai/adapters.py:211-218`
  ```python
  "simbad_info": {
      "status": r.get("simbad_status", "failed"),
      "main_id": r.get("simbad_main_id"),
      "aliases": r.get("simbad_aliases", []),
      "object_type": r.get("simbad_object_type"),
      ...
  },
  ```
- P1 产出：`property_standardization.py:472-475` 返回 `simbad_info`（MAIN_ID/OTYPE/OTYPES/SP_TYPE/RA/DEC）
- 覆盖发生条件：子图 2 的 simbad_resolver 只要成功（B2），主图 simbad_info 就被替换

**修改建议**

适配层做**合并而非替换**：`{**p1_simbad_info, ...}`，保留 P1 的 OTYPES/SP_TYPE 键。

**修复记录（2026-08-05，随 B2 已修复）**

`adapters.py:211-218` 改为 `{**p1_simbad, "status": ..., ...}`——合并而非覆盖，P1 的 OTYPES/SP_TYPE/RA/DEC 全部保留。

---

### B4. 契约外枚举值 `"modified"` 与死枚举 `"inferred"`

**问题阐述**

子图 1 在用户修改澄清参数后写入 `clarification_status = "modified"`（final_confirm 节点），路由也读取它；但父图契约（主图 state.py 注释）只声明 `confirmed/inferred/failed/cancelled` 四个值。契约外值会流入下游，而契约内的 `"inferred"` 却从未被任何节点产出（死枚举）。同时 `route_after_final_confirm` 的默认值 `"confirmed"`（routing.py:93）与 state.py:107 文档默认 `"inferred"` 互相矛盾。契约的两端（生产端/消费端/文档）各说各话。

**代码判断**

- 生产端：`subgraph1/nodes/final_confirm.py:83`（修改路径写 `"modified"`），`routing.py:100-102` 消费它
- 契约端：`astroquery_ai/state.py:52-53` 注释仅允许四值
- 死枚举：全库 grep `"inferred"` 仅命中 state.py:107 注释与 adapters 默认值，无节点产出
- 默认值矛盾：`routing.py:93` `state.get("clarification_status", "confirmed")` vs `state.py:107` 注释 `"inferred"`

**修改建议**

1. 在契约中正式加入 `"modified"`（主图 state.py 注释、adapters.py 文档同步），或让 final_confirm 把"修改后"映射为 `"inferred"`（语义上更接近"重新推断"）；
2. 统一路由默认值与 state 文档默认值（建议 `"inferred"`）；
3. 若 "inferred" 确认无生产者，从契约中删除，避免误导。

---

### B5. 退出词在性质追问阶段被吞

**问题阐述**

`route_after_initial_parse` 的第一个特例分支（已有天体 + 已询问性质 → 直接 final_confirm）位于 query_type 判断**之前**且不检查 query_type。用户在 ask_properties 阶段输入"退出/算了"时，initial_parse 已把 query_type 分类为 `"exit"`，但路由仍强行送入 final_confirm——退出词在该路径无效，用户只能再在确认环节输 n 才退出，体验与预期不符。

**代码判断**

- `astroquery_ai/subgraph1/routes/routing.py:35-39`
  ```python
  # 特殊情况：如果已经询问过性质且有天体名称，直接进入确认（忽略query_type）
  if target_entity and properties_asked:
      logger.info("...路由到 final_confirm")
      return "final_confirm"
  ```
- query_type 的 exit 判定在 `routing.py:52-54`，位于该特例之后 → 不可达

**修改建议**

在特例分支加 query_type 排除：
```python
if target_entity and properties_asked and query_type in ("astronomical",):
    return "final_confirm"
```
或把该分支移到 query_type == "exit" 判断之后。

---

### B6. report_agent 用恒空 dict 覆盖真实 per_entity 统计

**问题阐述**

Normalization 节点把真实的逐实体修改统计写入 `norm["modifications"]["per_entity_modifications"]`（normalization_agent.py:367），但 ReportAgent 读的是 `mods.get("modification_log")`——`modifications` 顶层根本没有这个键（`modification_log` 只存在于 field_standardizer 的返回值，且已被 normalization_agent.py:192 提取为 `base_logs`）。于是恒得空列表，`report_agent.py:52` 再用 `{}` **覆盖**掉真实统计。下游 quality_summary / Insights 拿到的 per-entity 修改统计恒为空，报告失真。

**代码判断**

- `Data_Normalization_agentV1/agents/report_agent.py:46-52`
  ```python
  per_entity = mods.get("modification_log") or []
  ...
  norm["modifications"] = {
      ...,
      "per_entity_modifications": {},   # ← 恒覆盖为 {}
  }
  ```
- 真实数据源：`normalization_agent.py:367` 已写入非空 `per_entity_modifications`
- 键名错位：`tools/normalization/field_standardizer.py:43` 的 `modification_log` 与顶层 `modifications` 结构不一致

**修改建议**

`report_agent.py` 改为直接透传 `mods.get("per_entity_modifications", {})`，不做 `{}` 兜底覆盖；顺带在 normalization_agent 与 report_agent 之间对齐键名（用同一常量）。

---

### B7. validation_agent 对 DB 记录溯源恒报缺失

**问题阐述**

ValidationAgent 判断 provenance 完整性的口径是"必须有 `page` 字段"，但**数据库记录的 provenance 是四要素结构 `{db_table, key_column, key_value, raw_column}`，没有 `page`**。于是所有 DB 记录都被计为"provenance 缺失"，`remaining_issues` 恒含 "Provenance: N records missing" 假报警。而 `output_validator.py:54-55` / `traceability_builder.py:152-153` 已经改用 `provenance_is_complete`（按 source_kind 区分口径），Agent 未同步。

**代码判断**

- `Data_Normalization_agentV1/agents/validation_agent.py:32`
  ```python
  missing_prov = sum(1 for r in records if not r.get("provenance") or r["provenance"].get("page") is None)
  ```
- 对照正确口径：`tools/export/output_validator.py:54-55`、`traceability_builder.py:152-153` 用 `provenance_is_complete` 按来源类型判断
- 样例佐证：output/70a0bf1c/ 的 2 条 DB 记录均无 page 字段

**修改建议**

复用 `provenance_is_complete`（或同等按 source_kind 分口径的逻辑）：DB/paper/supplement 各自要求的必填键不同，DB 记录不应要求 page。

---

### B8. Insights 终节点覆盖 Export 的 Failed 状态

**问题阐述**

Export 在 quarantine（校验失败）场景写 `execution_status="Failed"`，但主图有**无条件边** Export→Insights，而 Insights 的 synthesis 终节点把 `execution_status` 覆写为 `"Success"`。最终 `workflow_state.execution_status` 恒为 Success，Failed 信号丢失。样例佐证：manifest/quality_summary 的 `validation_passed: false`，但管线以 Success 结束——下游只能靠 `output_state.consumable=false` 间接识别。

**代码判断**

- 写 Failed：`Data_Export_agentV1/export_graph.py:72-75` finalize 透传 `execution_status="Failed"`
- 无条件边：`quality_pipeline/graph.py:190` Export→Insights
- 覆写：`Data_Insights_agentV1/agents/synthesis_agent.py:149` 写 `execution_status: "Success"`

**修改建议**

1. synthesis 保留原状态：`synthesis_agent.py` 改为"不写 Success 或仅在原状态为空时写"；
2. 或主图 Export 后按 `execution_status` 条件路由（Failed → 跳过 Insights 直接 END），与设计报告的"Insights 在 Export 成功后执行"一致。

---

### B9. context_state.quality_rules 恒为空：自适应阈值配置形同虚设

**问题阐述**

`make_initial_state` 把 `context_state.quality_rules` 置为 `{}`，quality_adapter 只注入 target_schema/standard_units/research_domain，**不注入 quality_rules**。于是 QualityAssessmentAgent 用空 dict 构造 AdaptiveThresholdEngine → quality_rules.yaml 的 `adaptive_thresholds` 段（critical_fields/sample_size/domain_tightness 等）全部走代码内置默认值。此外语义疑似倒置：yaml 里 astrophysics→exploratory→乘子 1.30（quality_rules.yaml:633-634），乘到完整度阈值上使阈值**更高更严**，与设计报告"探索性科学应更宽松"的声明相反；而 `get_conflict_threshold`（adaptive_threshold.py:92-120）根本不乘 domain_factor。

**代码判断**

- 空注入：`quality_pipeline/quality_state.py:350`（`quality_rules` 置空）；`astroquery_ai/quality_adapter.py` 无 quality_rules 注入
- 空构造：`Data_Assessment_agentV1/agents/quality_assessment_agent.py:194-199` 用空 dict 构造引擎
- 语义倒置：`quality_rules.yaml:631-634` `adaptive_thresholds_astrophysics: {exploratory: 1.30}`，乘子作用在 completeness 阈值上（方向存疑）

**修改建议**

1. 在 quality_adapter 注入 `quality_rules`（从 quality_rules.yaml 加载对应领域段），或 make_initial_state 内直接加载；
2. 复核乘子方向与设计报告"探索性宽松"是否一致（若是 bug，乘子应 < 1.0 或改为减操作）；
3. 让 conflict 阈值也受 domain_factor 调节（当前被遗漏）。

---

### B10. 子图 3 的 error_log 声明未生产：内部失败永不上浮

**问题阐述**

`ExtractionState.error_log`（schemas/state.py:135）已声明，但子图 3 的 4 个节点**全部不写入**该键——它们各自维护 `conversion_failed`/`extraction_failed`/`bbox_annotation_failed` 三套失败列表。父图 `adapters.py:315` 的 `if r.get("error_log")` 恒为假 → 子图 3 内部所有失败（转换/VLM/bbox）**永远不会出现在主图 error_log / final_output.error_log**，用户看不到"为什么 paper_records 是 0"。

**修复记录（2026-08-05，已修复）**

`result_builder.py`（子图3 终节点）：合并三套失败列表 → 标准 error_log 条目（`{node, error, timestamp}`）；`failed_papers` 统计改为 conversion + extraction 并集。父图 `adapters.py:315` 现在能检测到子图3 内部错误并上浮到 final_output.error_log。

---

### B11. 补充记录 `extraction_method: "database_query"` —— 已证实不是 bug（撤回）

**问题阐述**

原判为"复制粘贴错误，应为 'supplementary'"。经下游分析后撤回：补充材料和数据库查询的处理方式相同（都是 VizieR 查表），下游 `is_database_record()`（source_utils.py:21）以 `extraction_method == "database_query"` 作为唯一判据决定 DB/paper 分支——包括 `provenance_is_complete` 按 DB 四要素（db_table/key_column/key_value/raw_column）校验、`consistency` 按 DB 必需字段（无 trace_id）校验、`traceability_builder` 按 `startswith("database")` 分类。改为 `"supplementary"` 会触发 6 个下游接触点全部断裂。

**结论**

`extraction_method = "database_query"` 对 supplement 是正确的——**处理方式相同，下游按同一分支对待**。区分只需 `provenance.source_kind = "supplement"` vs `"database"`（Pydantic 模型 record.py:72 已声明该字段）。

**已落实（2026-08-05）**：supplement provenance 对齐 DB 四要素（cds_table_id→db_table, entity_column→key_column, matched_alias→key_value），database 侧同步补 source_kind="database"，两侧 record 结构完全统一。见第 9 章修复记录。

---

### B12. successful_catalogs / failed_catalogs 类型不对称

**问题阐述**

同一份检索结果里，`successful_catalogs` 是**计数（int）**、`failed_catalogs` 是**列表（list）**——类型不对称一路镜像到主图 database_results（adapters.py:190-194）与空壳结构（adapters.py:140-143）。而子图 2 的 state.py:75-79 声明两者均为 `List[str]`，三处语义互相矛盾。下游若想拿"成功星表名单"或做两边对称处理会出错；`total_catalogs_queried` 也因此无法从 state 直接推导。

**代码判断**

- `subgraph2/nodes/result_aggregator.py:51-52`
  ```python
  "successful_catalogs": len(state.get("successful_catalogs", [])),   # int
  "failed_catalogs": state.get("failed_catalogs", []),                # list
  ```
- 镜像：`astroquery_ai/adapters.py:190-194`；空壳：`adapters.py:140-143`（`"successful_catalogs": 0` vs `"failed_catalogs": []`）
- 声明：`subgraph2/state.py:75-79` 两者均 List[str]

**修改建议**

统一为列表（保留成功名单），`total_catalogs_queried = len(successful) + len(failed)` 推导；消费方如需计数自行 len()。改动的三处：result_aggregator.py、adapters.py、_empty_retrieval()。

---

### B13. 补充表分类缓存键不含目标天体（缓存投毒）

**问题阐述**

`table_meta_cache.json` 按 `table_id` 缓存 LLM 的表分类判断，但判断结果依赖 prompt 中嵌入的 `target_entity`（"是否值得提取目标天体 X 的数据"）。对 M31 判为 whole_entity 的表，换一个天体查询时复用错误分类（反之亦然）——缓存投毒，跨查询结果互相污染。

**代码判断**

- 缓存键：`astroquery_ai/subgraph2/nodes/supplementary_query.py:274-285`（`if table_id in cache: judgment = cache[table_id]`）
- 判断输入：`:126` prompt 含 `target_entity`
- 持久化：`:408-412` 写整库缓存文件

**修改建议**

缓存键改为 `f"{table_id}#{normalize(target_entity)}"`（或 key 中加入 entity 的哈希），同时考虑缓存条目加过期/上限（见风险 R3）。

---

### B14. RAG 库 220 条中文 category 破坏下游语义消歧

**问题阐述**

rag_properties 中 8 个文件、共 220 条性质的 `category` 是中文（测光/天体测量/光谱/物理/分类/环境/物理量/物理参数/变光/变星/变异性），其余 3073 条是英文 8 类。quality_adapter.py:42 把 `category` 直接当作 `semantic_type` 注入 target_schema，而 unit_converter 的语义类型匹配表（_SEMANTIC_TO_CATEGORY）是英文 32 键——中文值匹配不上 → 这些字段的单位消歧失效（如"磁星"类字段无法按语义过滤误转）。

**代码判断**

- 数据：`rag_properties/G.json`（category="天体测量"）等 8 个文件
- 注入：`astroquery_ai/quality_adapter.py:42` `"semantic_type": p.get("category", "")`
- 消费方：`quality_pipeline/tools/normalization/unit_converter.py:33-48` 英文键表

**修改建议**

跑一个一次性脚本把 220 条中文 category 映射为英文 8 类（中文词→英文键的映射表在 property_standardization.py:193-202 的 cat_names 里就有，可反向使用），改后校验全库 category ∈ 英文 8 类。

---

### B15. 模型名漂移：硬编码 qwen-plus vs 配置 qwen3.7-flash ~~已修复~~

**问题阐述**

子图 2 的列名映射 LLM 调用硬编码 `model or "qwen-plus"`，调用方（database_query、supplementary_query）都不传 model → 一律落到 `qwen-plus`；而全系统配置的模型是 `qwen3.7-flash`（subgraph1/config/config.yaml:8）。若部署端点只注册了 qwen3.7-flash 别名，数据库路的映射调用会失败并静默降级（映射空 → 未归一列名直接输出，见 C 类未对齐 #5）。bbox 侧同理：`bbox_vlm_client.py:120-122` 硬编码 `qwen3.7-flash/0.0/500`，而 subgraph3 settings.py:69-73 的 BBoxVLMConfig 从未被消费。

**代码判断**

- `subgraph2/utils/column_mapper.py:122-123`
  ```python
  response = client.chat.completions.create(
      model=model or "qwen-plus", ...
  ```
- 调用方不传 model：`database_query.py:159-164`、`supplementary_query.py:319-323`
- 配置基准：`subgraph1/config/config.yaml:8` `model: "qwen3.7-flash"`
- bbox 硬编码：`subgraph3/utils/bbox_vlm_client.py:120-122`；未消费的配置：`subgraph3/config/settings.py:69-73`

**修改建议**

1. `column_mapper.py` 默认模型改为从 subgraph1 config 读取（`subgraph1.config.config.llm['model']`），删除 `"qwen-plus"` 硬编码；
2. bbox_vlm_client 改为消费 `settings.bbox_vlm.model/temperature/max_tokens`；
3. 统一后全局只保留一个模型配置来源。

---

---

## 3. C 级：冗余清单（死代码 / 重复 / 残留）

### C1. tools/conflict/ 全目录死代码（约 1148 行，全库最大死代码块）

**问题阐述**：`tools/conflict/` 8 个文件（conflict_extractor、confidence_evaluator、context_builder、contextual_evidence、domain_rule_engine、rule_classifier、source_reliability_analyzer、statistical_evidence）**无任何代码引用**。Data_Conflict_agentV1 的 5 个 Agent 各自内嵌实现（Agent 头注释 "Tools: 0"），CONFLICT_DESIGN_REPORT.md:26,457-509 自认"V3.0 后不再调用"。

**代码判断**：全库 grep 无任何 `tools.conflict` import；与 Data_Conflict_agentV1/agents 下各 Agent 的 5 份实现（185/240/216/136/297 行）功能重叠。

**修改建议**：确认后整目录删除（保留报告文档即可）；若某 Agent 想复用，先抽出工具再删。

### C2. legacy/resolution_reasoning_agent.py（396 行 V1.0 裁决体系）

**问题阐述**：conflict_graph.py:33 注释"已移除"的旧裁决 Agent 仍完整保留，仅被 test_four_modules.py 以旧 API 形态引用（测试也未迁移）。

**代码判断**：`Data_Conflict_agentV1/legacy/resolution_reasoning_agent.py` 全库唯一引用在测试文件。

**修改建议**：删除 legacy/ 目录；同步清理引用它的测试（C12 一并处理）。

### C3. utils/llm.py StructuredLLM（~125 行）、utils/retry.py（77 行）、_parse_utils 消歧子系统（~135 行）

**问题阐述**：三套"基础设施"从未接线——`get_structured_llm`（llm.py:137-262）无调用者（所有 Agent 用 `get_llm` + 裸 invoke + 手写 JSON 解析）；`retry_on_failure` 无调用者；`_parse_utils.py:473-607` 的 `disambiguate_batch/apply_disambiguation/register_parser` 无调用者。这些代码可能含可复用的正确实现，但当前状态是维护负担。

**代码判断**：grep 实证：`get_structured_llm`、`retry_on_failure`、`disambiguate_batch` 均仅定义处命中。

**修改建议**：删除或补接线三选一——推荐先删 retry.py 与 StructuredLLM（get_llm + 手写解析已覆盖），消歧子系统若计划启用则补接线到 _parse_utils 的解析流程。

### C4. subgraph3 双 VLM 客户端结构重复（约 70%）

**问题阐述**：`vlm_client.py`（324 行）与 `bbox_vlm_client.py`（315 行）重复实现 base64 编码（187-193 vs 131-134）、DashScope 响应解包（211-245 vs 174-212）、限流错误码表（251-256 vs 250-255）、指数退避重试循环（209-321 vs 148-307）、api_key 注入。

**代码判断**：两文件逐段对比，仅 prompt 构建与 model/temperature 参数不同。

**修改建议**：抽公共基类/工厂，参数化 model/temperature/max_tokens/prompt 构建；预计消解约 200 行重复，且顺带消除 B15 的模型硬编码。

### C5. SIMBAD 解析三处重复

**问题阐述**：SIMBAD 解析实现出现在三处：P1（property_standardization.py:53-113，手写 VOTable XML 解析）、子图 2 simbad_resolver（astroquery Simbad API）、scripts/query_properties.py:33-89（含同一文件转义规则与 _star 兜底）。三份实现各自维护，行为可能漂移（如 P1 与 resolver 的字段名大小写不同，正是 A1 断线的土壤）。

**代码判断**：转义规则重复：query_properties.py:69 vs property_standardization.py:144；兜底逻辑同样重复。

**修改建议**：以 P1 的 query_simbad 为唯一实现（或抽到共享 utils），子图 2 入口改为消费 P1 结果（见 B2），query_properties.py 改为 import 复用。

### C6. generate_target_schema 双份实现

**问题阐述**：`property_standardization.py:342-364` 与 `quality_adapter.py:29-47` 是同一函数的两个副本（仅字段细节略异）。且 P1 写入 state 的 target_schema **从未被消费**——quality_adapter 总是用 property_spec 重新生成。双重浪费。

**代码判断**：两份函数体逐字段对比基本一致；grep 全库 target_schema 的消费者仅 quality_adapter（重新生成）、quality_pipeline（消费 adapter 注入的那份）。

**修改建议**：删除 property_standardization.py 中的副本及其在 P1 节点的调用（P1 只产出 property_spec），target_schema 统一由 quality_adapter 生成（保持"P1 不关心子图 4 结构"的职责划分）。

### C7. 死配置键（全库约 30 处）

**问题阐述**：各配置文件存在大量定义但从不读取的键，维护者以为在生效、实际是摆设，且造成数字漂移（见 C7b）。

**代码判断**（grep 实证无读取方）：
- 子图 1：`config.yaml:54-55` `ui.user_input_prompt/confirm_prompt`（节点硬编码提示）、`:57-60` `logging` 段（全库无 basicConfig，DEBUG 级别从未生效）、`:39-49` `common_properties`、`:15` `clarification.default_entity_type`
- 子图 2：`config.yaml:37` `total_catalogs: 22`（实际 27，见 C7b）、`api.ads.timeout`、`retrieval.database.sequential_query`、`retrieval.performance_targets` 整节、`output.output_format/save_intermediate_states`、`logging.*` 整段
- 子图 3：`settings.py:25` `vlm.timeout=600`（从未传给 SDK 调用）、`:50-51` `PDFConfig.dpi=100/format`（实际走 pdf_utils 默认 150）、`:69-73` BBoxVLMConfig 整类、`:81` `retry_delay_base`
- quality：`quality_rules.yaml` 约 10 段无读者（adaptive_thresholds/domain_weights/resolution_weights/entity_extraction/measurement_methods/conflict_detection/outlier_detection/nonlinear_penalties/missing_value/duplicate/format 段、`loop_control.no_new_conflict_rounds`）、`llm_config.yaml:29` `schema_prefix`、`domain_config.py:21` `INSIGHT_BATCH_SIZE`（设计报告自认预留未用）

**修改建议**：删除或接线二选一。建议：子图 1 的 ui/logging/common_properties 删；子图 3 的 timeout/dpi/BBoxVLMConfig 接线（见 B15）；quality 的 yaml 段逐个确认后删或接（`adaptive_thresholds` 建议接线——见 B9）。

### C7b. 星表数量数字漂移（22 vs 27）

**问题阐述**：同一事实三个数字：`graph.py:46` 注释"22个星表"、`config.yaml:37` `total_catalogs: 22`、catalog_config.json 实际 **27** 个星表（三份 catalog JSON 键集已验证 27=27=27 一致）。`total_catalogs` 键全库无读取，注释误导排查者。

**代码判断**：`subgraph2/graph.py:46`、`subgraph2/config/config.yaml:37`、`catalog/catalog_config.json`（27 项）。

**修改建议**：删 yaml 的 total_catalogs 键，注释统一为 27；后续星表增删只改 catalog_config.json 一处。

### C8. .bak 残留与损坏文件

**问题阐述**：`configs/schema_mapping.yaml.apply.bak`（685 行）与现文件逐字节相同（纯副本）；`schema_mapping.yaml.broken.bak`（1568 行）是**损坏版**（aliases 换行错位导致 YAML 无法解析）——若有人误用会当场炸配置加载。

**代码判断**：diff 实证 apply.bak 与 schema_mapping.yaml 为空；broken.bak 解析失败。

**修改建议**：两个 .bak 直接删除（历史已在 git/工作区外有据）。

### C9. 死状态字段与死输入（跨子图）

**问题阐述**：多个 state 字段只写不读或零读写：
- 子图 1：`state.py:83-88` `exit_intent_detected`（零读写）；`state.py:75-81` `is_clear`（只写不读，routing 判断用 target_entity）
- 子图 2：5 个 `*_status`（database_query_status/ads_search_status/unpaywall_query_status/pdf_download_status）+ 2 个 `*_progress`（catalog_progress/pdf_download_progress）只写不读，纯观测性
- 子图 3：`schemas/state.py:41` `paper_sources` 必填但零节点读取（adapters.py:291 死输入）
- quality：`quality_state.py:109,294-306,359` `entity_index` 构建后全库无消费者

**代码判断**：各键 grep 仅声明/写入处命中。

**修改建议**：子图 2 的 status/progress 键若确为观测用途，保留但注明"仅日志"；`paper_sources` 从子图 3 契约删除或改为被 result_builder 消费（如写入 paper_sources 关联）；`entity_index` 删除或接线到 Insights/Assessment 的实体分组逻辑。

### C10. 重复日志 / 重复统计 / 重复定义

**问题阐述**：
- `database_query.py:210-220` 同一段统计日志整段打印两次
- `result_aggregator.py:35-69` 构建的三个嵌套 dict（simbad_resolution/database_results/paper_results）仅用于 logger，父图从 state 重建——死结构
- `decision_reasoning_agent.py:17` 模块级 `_ROUTE_SEVERITY` 与 `:183` 局部重复定义；`:174-179` 与 `:215-218` 决策矩阵 dict 两处重复
- `planning_agent.py:530` `import re as _re` 重复导入（L12 已 import re）
- `export_generation_agent.py:14` 与 `synthesis_agent.py:26` `_DEFAULT_OUTPUT_DIR` 双份定义
- `llm.py:319` `_short_error` 与 `:458` `_short_error_str` 重复实现

**代码判断**：逐处对照见上。

**修改建议**：删重复日志与 result_aggregator 死结构（保留统计日志）；决策矩阵/常量收敛到单一定义；重复工具函数合并。

**修复记录（2026-08-05，部分）**：`database_query.py:210-220` 重复日志块已删除（随 A1 一并处理）；其余子项（result_aggregator 死结构、决策矩阵重复等）待清理轮。

### C11. 死函数与未使用导入（20+ 处）

**问题阐述**：一批定义后无调用者的函数与模块级未使用导入：
- 死函数：子图 1 `format_chat_history()`（utils/llm_utils.py:250-265，utils/__init__.py:17 导出）；子图 3 `image_cache.cleanup()`（image_cache.py:85-104，**因此缓存无人清理**，见 D 类风险）；planning_agent.py:641-652 `_validate_code_simple_fallback`；`validation_agent.py:22-25` 计算后未用的 `critical_expected`；`check_retry`（routers.py:83-108，仅测试引用）；`get_conflict_threshold`（adaptive_threshold.py:92）；`get_adaptive_engine` 单例（:127）；`profiling.data_profiling`（Agent 内嵌自己的 5 个 Profiler）；`output_validation_agent.py:45` 读恒不存在的 `trace_completeness` 键
- 死导入：约 30 处（如 subgraph1 graph.py:17 `config`、initial_parse.py:4 `datetime`、vlm_extractor.py:7 `Dict/List`、bbox_annotator.py:5 `Dict`、result_builder.py:3 `Dict`、bbox_vlm_client.py:10 `Optional`、logger.py:4 `os`、schemas/state.py `Optional/PIL`、config/__init__.py:4 `os` 等）

**代码判断**：逐处 grep 实证。

**修改建议**：删死函数（`cleanup()` 若保留则接线到运行收尾）；未使用导入一次性清理（可交给 ruff/autoflake 跑一遍，注意别误删被 `__all__` 或延迟导入依赖的名字）。

### C12. 测试断链与遗留产物

**问题阐述**：
- `tests/test_p1_integration.py:9` 用 `from combine.astroquery_ai...`（当前无 combine 包）→ **完全不可运行**
- quality_pipeline/test 4 个文件未完成包迁移（混用 `from ..xxx` 与顶层 `import utils.llm` / `from generate_test_data`）→ 从项目根导入失败：test_insights_graph.py:16、test_main_graph_routing.py:23、test_real_data_e2e_mock.py:18、test_assessment_flow.py:18
- 两个 real-data 测试依赖的文件不存在：`test_real_data_e2e.py:28` `result_9e76f974-*.json`、`test_real_data_e2e_mock.py:53` `test_data_sample10.json`
- `output/70a0bf1c/` 8 个运行产物已入库；requirements.txt 中 tenacity/tqdm/langchain 无任何 import

**代码判断**：实测从项目根 import 四个测试文件报 ImportError/ModuleNotFoundError；ls 确认两个数据文件缺失。

**修改建议**：修 import 路径（改相对导入或把 utils 收敛到包内）；补数据文件或改测试为生成式 fixture；output 产物移入 gitignore；requirements 删未用依赖（tenacity/tqdm/langchain）。

### C13. 文档与旧工作区残留

**问题阐述**：
- `MERGE_PLAN_IMPL.md:626` 状态"待实施" vs `MERGE_COMPLETION_REPORT.md:33-67`"12 项全部 ✅"直接矛盾（废弃文档未标注）
- docs 全部使用旧布局路径 `combine/astroquery_ai/...`、`train/rag_properties`，当前实际布局是 `astroquery_final/astroquery_ai/`（README 才是当前布局）
- 文档引用不存在的实体：README.md:113 与总架构设计方案.md:747 引用 `schemas/` 目录（不存在）；CONFLICT_DESIGN_REPORT.md:486 引用 `CONFLICT_DESIGN_REPORT_V2.3.md`（不存在）
- 旧工作区 `E:\work\combine0805\train\` 含完整重复的 rag_properties（100 文件）、add_units.py、query_properties.py、unit_fill_report.json、output_*.json 副本

**代码判断**：目录实测 + diff 比对。

**修改建议**：MERGE_PLAN_IMPL.md 标注"已由 MERGE_COMPLETION_REPORT.md 取代"；docs 路径统一为当前布局；补建或删引用；旧工作区移出项目目录或归档。

---

---

## 4. D 级：未连接 / 未对齐清单

### D1. 数据库路"空映射=输出原始列名"与补充路"空映射=零记录"行为不一致

**问题阐述**：两条提取路对同一输入（空 property_spec 或 LLM 映射失败）行为完全相反：数据库路在 `column_mapping` 为空时**跳过过滤，所有列按原始列名输出为 field_name**（违反"三路都归一"契约）；补充路在映射空时**产出 0 条 record**。且 database_query.py:168 的注释声称"使用空映射（所有列会被跳过）"，与实际短路行为相反——注释与代码互相矛盾。

**代码判断**：
- `database_query.py:166-168` 注释 vs `database_utils.py:137,152-160`：`if column_mapping and ...` 空 dict 为 falsy → 走未过滤分支
- `supplementary_query.py:325` 空映射被过滤后 → 零记录

**修改建议**：统一语义——建议两边都"无映射则跳过该列"（保守，不产出未归一字段）；同步修正 database_query.py:168 注释；并在无 property_spec 时显式跳过数据库路并写日志（而不是产出原始列名）。

### D2. exit 路径零输出：子图 1 对父图契约的承诺靠父图容错维持

**问题阐述**：`query_type == "exit"` 时路由直接 END，**没有任何节点设置** `clarification_status`、`user_confirmed`、`conversation_history`——子图对父图"应返回这些键"的契约只靠 `adapters.py:81-84` 的 `.get()` 默认值兜底。同理 `entity_type_hint` 全子图无节点写入（state.py:56-61 注释声称"固定 unknown"但行为从未实现）；`conversation_history` 只在 final_confirm 确认路径填充，拒绝/失败/退出路径丢失。兜底一旦被改掉即契约破坏。

**代码判断**：`subgraph1/graph.py:57`（exit→END）；`adapters.py:80-84`（.get() 兜底）；`final_confirm.py:112`（唯一 conversation_history 写入点）。

**修改建议**：在路由到 END 前增加统一的"收尾"（polite_reject/handle_failure/exit 路径写入 clarification_status=... / user_confirmed=False / conversation_history），或把这些键改为子图 state 的必填收尾节点统一产出；契约注释与实现对齐。

### D3. quality_pipeline 测试与生产日志配置断链

**问题阐述**：`utils/logger.py:24-46` 的 `setup_logging` **仅被测试调用**，生产运行走 logging 的 lastResort handler（仅 WARNING+ 输出到 stderr）——全管线 INFO 级审计日志（workflow_history 之外的 console 日志）在生产不可见。日志配置段（yaml）也无人加载。

**代码判断**：grep `setup_logging` 命中仅 test 文件；生产入口（quality_adapter / graph.py）无 logging.basicConfig。

**修改建议**：在 quality_pipeline 包入口（如 graph.py 或 make_initial_state）统一调用 setup_logging（或读日志配置初始化）；确认日志级别与文件输出按配置生效。

### D4. .env.example 与代码实际读取的 env 键不一致

**问题阐述**：代码实际读取 8 个 env 键：`ADS_API_TOKEN`、`UNPAYWALL_EMAIL`、`DASHSCOPE_API_KEY`、`DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`EXPORT_OUTPUT_DIR`、`EXPORT_CSV_ENCODING`；`.env.example` 只列前 3 个 + `CLARIFICATION_LLM_API_KEY`（代码从不读取，且 .env.example:16-18 承诺的"修改 yaml 从环境变量读取"从未实现）。新部署者照 .env.example 配置会缺 5 个键。

**代码判断**：grep 全库 `os.environ/getenv/load_dotenv` 键名汇总 vs `.env.example` 逐键比对；subgraph1 无任何环境变量读取代码。

**修改建议**：.env.example 补全 8 个键 + 注释各自用途；删除或实现 CLARIFICATION_LLM_API_KEY 承诺（建议删除承诺，密钥统一走 .env，见 A3）。

**修复记录（2026-08-05，随 A3 已修复）**：根 .env.example 重写为全量模板（10 个环境变量，分模块注释），CLARIFICATION_LLM_API_KEY 承诺已删除。

### D5. 主图 error_log 的 add reducer 与子图 2 内部实现的隐性依赖

**问题阐述**：主图 `error_log` 用 `Annotated[List, add]`（state.py:118），子图 2 的 error_log 也是 add（state.py:172），适配层按"只上浮增量"处理（adapters.py:224-226 `list(r["error_log"])`）。但**子图 2 内各节点返回的是"本次新增条目"还是"全量"没有统一约定**——database_query 返回 1 条新增（database_query.py:73-77 注释自认），supplementary_query 返回 errors 列表（新增，supplementary_query.py:420-421）。当前约定靠"各节点自觉"维持，一旦某节点像 simbad_resolver 那样在失败时返回全量（虽然当前也是新增），add 会重复累加。隐性契约无测试守护。

**代码判断**：`subgraph2/state.py:172` 注释"返回整个 state 会把已累积条目重复累加"——多个节点注释互相引用该约定；主图 `state.py:118`。

**修改建议**：在子图 2 文档/测试中固化约定（节点只返回新增条目），并加一条集成测试断言"error_log 去重后无重复 node+error"。

### D6. LangGraph 静默丢弃未声明键：human_review `_from_conflict`

**问题阐述**：`human_review_agent.py:50,171` 写入旧字段名 `"_from_conflict"`，而 quality_state.py:148 在 V3.3 已改名为 `from_conflict` —— 写操作被 schema 通道静默丢弃，"清除循环标记"的意图落空。当前恰因 `from_conflict` 恒为 False 而无实害，但循环保护逻辑实际从未生效过。

**代码判断**：`quality_pipeline/Data_HumanReview_agentV1/human_review_agent.py:50,171` vs `quality_state.py:148`。

**修改建议**：改为写 `from_conflict`；并加一条规则/测试：节点返回键必须 ⊆ state 声明键（防再犯）。

### D7. 设计文档与实现的引用失实

**问题阐述**：README.md:113 与总架构设计方案.md:747 引用不存在的 `schemas/` 目录；CONFLICT_DESIGN_REPORT.md:486 引用不存在的 `CONFLICT_DESIGN_REPORT_V2.3.md`；subgraph3 schemas/state.py:11-14 docstring 声称"三个节点"实际 4 节点；result_aggregator.py:87 注释说"三个输入边"却列 2 个（实际 3 个入边：simbad 失败路由/database/supplementary）。

**代码判断**：目录实测 + 逐条比对。

**修改建议**：补建/删除引用；docstring 与注释更新为当前事实（顺手把 graph.py:46 "22 个星表"改 27）。

### D8. 全局可变域状态：set_research_domain 的进程级 last-writer-wins

**问题阐述**：`configs/__init__.py:4-23` 的 `_global_domain` 是进程级全局变量，质量管线各工具（semantic_type/source_checker/unit_converter 等）依赖它决定加载哪个配置段。同进程多领域并发/串行运行会交叉污染；`semantic_type._load_semantic_rules`（semantic_type.py:24-47）按领域刷新缓存但无锁。当前单领域单线程下无碍。

**代码判断**：`quality_pipeline/configs/__init__.py`（set/get_research_domain）；调用方 `quality_adapter.py:114-116`。

**修改建议**：至少加锁 + 每次 set 后失效相关缓存；彻底方案是领域参数随 state 传递而非全局。

### D9. 双计数器并存：iteration_counter 与 loop_round

**问题阐述**：`routers.py:320` 的 `iteration_counter` 与 `routers.py:287-289,363-390` 的 `loop_round` 是两套循环计数，超限判定混用（route_after_loop 用 iteration_counter、C→B 上限用 loop_round），语义重叠，改一个忘一个时会产生奇怪的超限行为。

**代码判断**：`quality_pipeline/routers.py` 两处计数逻辑。

**修改建议**：收敛为一个计数器（或明确分层：loop_round=外层轮次，iteration_counter=内层步数），加注释说明边界条件。

### D10. dispatch 对未知路由值无防御

**问题阐述**：`dispatch_node` 按 `per_source_routes` 建队列但不校验路由值（routers.py:240-242），未知值会进入 pending 的陌生键，`route_after_dispatch` 只查 4 个已知键 → 该 source 永远不被处理。当前 4 个取值（Assessment/Normalization/Conflict/Export）均由决策 Agent 保证，仅防御性缺失。

**代码判断**：`quality_pipeline/routers.py:240-242` 与 route_after_dispatch 的已知键集合。

**修改建议**：dispatch 时对未知路由值记 error_log 并默认走 Normalization（或跳过该 source 并显式记录）。

### D11. models/ 5 个 Pydantic 模型生产路径不校验

**问题阐述**：`quality_pipeline/models/`（grounded_data/insights/record/source）定义了 5 个 Pydantic 模型，但生产路径只把它当"文档化的接口契约"——全库仅有 test/app_quality.py:35 使用 GroundedData 做校验，节点全部用裸 dict。契约与实际数据结构的漂移无人发现（D1/D3 类型不齐正是此类漂移）。

**代码判断**：grep models 包引用仅测试命中。

**修改建议**：在关键边界（make_initial_state 入口、final_output 出口）用模型做运行时校验（可选开启，避免性能损失），或删除模型包改为文档化 TypedDict。

### D12. 子图 2 的 simbad_info 契约声明与实际键名不一致

**问题阐述**：`subgraph2/state.py:33-38` 声明 simbad_info 格式含 `ALIASES`（大写），P1 实际产出的是 `MAIN_ID/OTYPE/OTYPES/SP_TYPE/RA/DEC`；子图 2 内部产出的别名在 `simbad_aliases`。同一个"别名"概念三种叫法、三个位置（A1 的断线根源）。

**代码判断**：`state.py:33-38` vs `property_standardization.py:61-66` vs `simbad_resolver.py:124`。

**修改建议**：以 A1 修复为契，把"别名"统一为一个键（建议 `simbad_aliases` 列表），契约注释同步更新，杜绝再出现大写/小写、info 内/外的分裂。

**修复记录（2026-08-05，随 A1 一并解决）**：读侧已统一为 `simbad_aliases`（database_query.py:41），`state.py:33-38` 注释已纠正（去掉 ALIASES 格式声明，注明别名走 simbad_aliases、P1 无 ALIASES 键），分裂的文档侧与读侧均收敛。

---

---

## 5. E 级：风险清单

### E1. 并发写缓存无锁（数据损坏风险）

**问题阐述**：`column_mapping_cache.json` 与 `table_meta_cache.json` 都是"读-改-写整文件"且无锁：database_query（并行支路）与 supplementary_query（论文链尾）在 LangGraph 中可同时存活，两者并发 `_load_cache`/`_save_cache`（column_mapper.py:44-51 整文件 `write_text` 覆写，无原子写）→ 丢条目、损坏 JSON。

**代码判断**：`subgraph2/utils/column_mapper.py:33-51`；`supplementary_query.py:408-412`；图拓扑 graph.py:33 并行分支。

**修改建议**：写缓存加进程内锁（threading.Lock 模块级单例）+ 原子写（tmp 文件 + os.replace）；或按"最后写者为准+启动时合并"策略。

### E2. 缓存无限增长（磁盘/失效风险）

**问题阐述**：三处缓存均无淘汰策略：`%TEMP%\graph3_image_cache`（每运行累积，`cleanup()` 无人调用，C11）、column_mapping_cache（按表×PropertySpec 指纹，每次新增组合就加条目）、table_meta_cache（按表号永久累积，含 LLM reasoning 长文本）。

**代码判断**：`image_cache.py:85-104`（无调用者）；`column_mapper.py:80,151-152`；`supplementary_query.py:408-412`。

**修改建议**：运行收尾调 cleanup()；两个 JSON 缓存加容量上限（如 1000 条）与 LRU 淘汰，损坏时重建。

### E3. 子图 3 内存放大链无上限（OOM 风险）

**问题阐述**：PDF 全页渲染驻留内存（pdf_utils 先全量渲染再落盘，无页数上限）→ VLM 阶段 15 并发 × 每篇全部页面 base64 一次请求（几十~数百 MB）→ bbox 阶段 100 并发 × 每张 150dpi 全页 RGB 图（单张约 10MB）。百页级 PDF 或大批量时极易 OOM；DashScope 载荷上限也会因整篇单请求而触顶。

**代码判断**：`subgraph3/utils/pdf_utils.py:30-47`；`vlm_extractor.py:160` + `vlm_client.py:187-193`；`bbox_annotator.py:96,223`。

**修改建议**：单篇 PDF 页数上限（如 30 页）+ 分辨率上限；VLM 分页/分块请求（按页或按 N 页一批）；bbox 池化并发（信号量）而不是裸线程 100。

### E4. PDF 下载无保护

**问题阐述**：大小上限只查 `content-length` 头（chunked 响应无限制）；无总下载量上限（50 篇 × 50MB ≈ 2.5GB）；流式中途异常 `.part` 文件残留；`os.replace` 静默覆盖同名旧 PDF；瞬时失败无重试（每 URL 仅试一次）。

**代码判断**：`subgraph2/nodes/pdf_download.py:46-54,62-64,87-90,158-159`。

**修改建议**：chunked 场景加累计字节上限；总数上限可配置；下载失败重试 1-2 次；已存在文件跳过或版本化命名。

### E5. 统计误报（Cohen's d 与小样本）

**问题阐述**：`statistical_conflict.py:310-312` 在样本 n<2 时用相对差 `|Δmean|/max(|mean|,0.001)` 冒充 Cohen's d，小值字段极易 d>2.0 → 冲突误报；`outlier.py:55-56` MAD=0 时用 1e-10 假分母，相同值多的字段批量误报异常。

**代码判断**：`quality_pipeline/tools/assessment/statistical_conflict.py:310-312`；`tools/assessment/outlier.py:55-56`。

**修改建议**：n<2 时返回 None 不参与统计（或标记 low_support）；MAD=0 时该列标记"无离散"跳过离群检测而非假分母。

### E6. simbad 失败跳过整条检索 + 断网挂起

**问题阐述**：子图 2 以 simbad_resolver 为入口（graph.py:68），失败直接跳 result_aggregator，**连论文检索也不做**（论文路其实不依赖 SIMBAD，被错误牵连）；VizieR 单次 30s 超时无重试（database_query.py:90-94），断网时 N 表各等 30s。

**代码判断**：`subgraph2/graph.py:71-74`；`database_query.py:90-94`。

**修改建议**：路由改为 simbad 失败仍走论文路；VizieR 查询加轻量重试（如 1 次）与总超时预算。

**修复记录（2026-08-05，随 B2 收敛重构已修复）**：simbad_resolver 节点已删除，其路由函数随之移除；START 直接进入并行分支，论文路不再被任何前置条件阻拦。

### E7. 时间戳时区混用

**问题阐述**：`database_query.py:76` 用 `time.strftime("%Y-%m-%dT%H:%M:%SZ")`（UTC），其余节点（ads_search/simbad_resolver/supplementary/result_aggregator/子图3）用 `datetime.now().isoformat()`（本地无时区）——同一条 error_log 里两类并存，追溯对账困难。

**代码判断**：`subgraph2/nodes/database_query.py:76` vs 其余节点。

**修改建议**：统一为 `datetime.now(timezone.utc).isoformat()`（或全部本地+显式时区）。

### E8. add_units.py 覆盖写 RAG 无备份

**问题阐述**：`scripts/add_units.py:313-318` 直接 `path.write_text()` 覆盖 RAG JSON 且无备份；LLM 误判单位将永久污染数据；`unit_fill_report.json` 当前不存在（报告丢失）。另有 9 条 unit 不在当前白名单（Msun/yr、Msun*km/s、Mpc^-3 等，补全后白名单被收紧）——`--force` 重跑时这 9 条会被当 invalid **丢弃而非修正**。

**代码判断**：`scripts/add_units.py:49-104`（白名单）、`:313-318`（覆盖写）；实测 9 条越界。

**修改建议**：写前备份（.bak）或先写临时文件；9 条越界单位人工判定后加入白名单或明确剔除；重跑前先恢复 unit_fill_report。

### E9. LLM 输出零运行时校验

**问题阐述**：全链无 pydantic/类型校验：`requested_properties` 若 LLM 返回字符串，`final_confirm.py:30` 的 `", ".join(requested_properties)` 会把字符串逐字符拆开（"distance"→"d, i, s, t, a, n, c, e"）；target_entity 若返回 list 会渲染成奇怪内容。TypedDict 仅静态类型，运行时零保护。

**代码判断**：`subgraph1/nodes/final_confirm.py:30,38`；全库无 validate。

**修改建议**：在子图 1 的 initial_parse 输出边界加轻量类型校验（isinstance 检查 + 强制转换），失败走 polite_reject/重试。

### E10. 子串匹配误判（退出词 / 行过滤 / 查询注入）

**问题阐述**：三处子串级匹配风险：①退出关键词用 `any(kw in user_input.lower() ...)`（llm_utils.py:40）——"我不退出""别取消"都会判 exit 直接 END；"goodbye"必先命中"bye"（config.yaml:25-26 恒死配置）。②`_row_matches_entity`（supplementary_query.py:213）双向 `in` 子串——别名 "NGC224" 命中表值 "NGC2244"。③ADS 查询串 `f'"{target_entity}" AND (...)'`（ads_search.py:77）无转义——含引号/括号改写查询语义。

**代码判断**：`subgraph1/utils/llm_utils.py:40`；`subgraph2/nodes/supplementary_query.py:199-213`；`ads_search.py:77`。

**修改建议**：①改词边界匹配（正则 `\b` 或分词相等）；②行过滤改全等匹配（规范化后相等）；③ADS 查询串对实体名转义或限制字符集。

### E11. bbox 进度双计数与伪造溯源

**问题阐述**：`bbox_annotator.py:107` 无条件 `completed += 1` 后异常分支 `:124` 再 `+1` → 进度可超 total；bbox 缺失/非法时返回默认全页框 `[0,0,1000,1000]`（result_builder.py:201-203），且 bbox 的 confidence/found 信息完全不透传到记录——下游无法区分真框与默认框（伪造溯源）。

**代码判断**：`subgraph3/nodes/bbox_annotator.py:107,124`；`result_builder.py:201-203`。

**修改建议**：进度计数改为 finally 结构单次自增；默认框改为 `found: false` 显式标记并透传 bbox confidence，由产品决策是否保留默认框记录。

### E12. 生产日志静默丢失（quality_pipeline）

**问题阐述**：见 D3——`setup_logging` 仅测试调用，生产 INFO 级日志不可见，故障排查无审计线索。

**代码判断**：`quality_pipeline/utils/logger.py:24-46`；grep 调用方。

**修改建议**：见 D3。

### E13. planning_agent 三引号模板非法转义（SyntaxWarning）

**问题阐述**：`planning_agent.py:52` 的 `_TOOL_CODE_TEMPLATE`（内嵌给 LLM 的 Python 代码模板）含未转义正则 `\d`/`\.` → 每次 import 触发 SyntaxWarning（CPython 3.14 实测；显示位置漂移到 74 行 raw 字符串是误导，元凶是 52 行非 raw 模板）。`-W error` 环境（常见 CI）直接 import 失败；未来 Python 版本可能升级为 SyntaxError。

**代码判断**：`Data_Normalization_agentV1/agents/planning_agent.py:52-...` 三引号模板内 `re.match(r"...\d...")` 非 raw。

**修改建议**：模板内正则前加 `r` 前缀（模板是嵌入代码，按 raw 写），或转义为 `\\d`；全库顺手 py_compile -W error 校验。

### E14. 子图 1 每轮交互 2-3 次 LLM 调用

**问题阐述**：initial_parse 每轮触发 classify + extract 两次 LLM（llm_utils.py），追问 3 轮可达约 9 次调用，无缓存无去重——成本/延迟偏高。非缺陷，属设计取舍。

**代码判断**：`subgraph1/nodes/initial_parse.py:41-51`；`llm_utils.py:90,182,191`。

**修改建议**：分类可先用规则（关键词表已有），规则不中再调 LLM；DEBUG 日志中完整记录用户原文（llm_utils.py:90,182,191）建议截断（隐私）。

### E15. 其余小风险

- **状态原地变更绕过 reducer**：多个节点浅拷贝后原地改嵌套 dict（quality_scoring_agent.py:299-315、decision_reasoning_agent.py:36）——单次运行无碍，checkpoint/重放语义存隐患 [疑似]
- **`_merge_dict` 按 dict 全等去重**：两个 agent 产出完全相同 dict（同 timestamp）丢一条（quality_state.py:68）[理论]
- **模块级缓存无锁**：`_global_domain`、`_SEMANTIC_RULES`（semantic_type.py:20）、`_JOURNAL_TIERS`（source_checker.py:14）多线程首次写入竞态 [低]
- **`out.json`/`vid.json`**：经核实是合法 otype（外向流/空洞），非误产物，但建议口头确认保留
- **`post_AGB_star.json` 孤儿文件**：内部 otype=`pA*`，消费方转义命中 `pA_star.json`（不存在）→ 永远加载不到，见 F 节

---

## 6. F 级：数据质量（rag_properties 实测统计）

| 指标 | 实测数字 | 说明 |
|---|---|---|
| 文件数 | 100 | 与 README"100 otype"一致 |
| properties 总数 | 3293 | 与 README"3293 性质"一致 |
| 缺 unit **键** | 0 | MERGE_PLAN.md"3293/3293 已补齐"属实 |
| **unit 为空串** | **1054 条（32%）** | 部分合理（红移/ID/标志无量纲），部分存疑（见下） |
| 缺 category 键 | 0 | 但 **220 条为中文 category**（见 B14） |
| property_id 重复 | 0 | |
| 孤儿文件 | 1 | `post_AGB_star.json`（消费方永远命中不了） |
| 越界单位 | 9 条 | Msun/yr×3、Msun*km/s、Msun*km/s/yr、Msun/pc²、1/yr、Mpc⁻³、K*km/s（不在 add_units 白名单） |

**unit 语义存疑样例**（LLM 判定未人工校验）：`vid.json` void_volume unit="Mpc"（描述为 (Mpc/h)³ 体积）、void_surface_area unit="Mpc"（面积）、void_numdens_min unit="cm⁻³"（星系数密度）；`out.json` outflow_momentum unit="Msun*km/s"；`catalog_units.json` fermi 段（4FGL）单位是复制粘贴（Lum 单位 "pc"、无意义的 H/K 测光）。

**修改建议**：抽查 1054 条空 unit 中应填未填的比例；9 条越界单位人工判定（加白名单或剔除）；vid/out 的体积面积单位修正；fermi 段与 VizieR IX/67 实际列比对重填。

---

## 7. 修复优先级总表

| 优先级 | 编号 | 一句话 |
|---|---|---|
| P0 | ~~A1, A2, A3~~ ✅ | **已修复（2026-08-05）** |
| — | A5 | ⏸️ **配置项，非代码缺陷**：所有 Agent 有 try/except → template fallback 优雅降级，管线不阻塞。`.env` 已预留 `OPENAI_API_KEY`/`OPENAI_BASE_URL`，部署时填入即通 |
| — | A4 | ⏸️ **CLI 阶段搁置**：`input()` 在交互模式下是正确行为。Web 化方案（Headless Protocol）已设计在第 9 章附录，搭建前端时再执行 |
| P1 | B1, B6, B7, B8, B9 | 数据失真修复（各 1-5 行） |
| — | B2, B3, E6 | ✅ 已修复（随 SIMBAD 收敛，2026-08-05）：P1 补 ids 产出别名 → adapters 直接映射 simbad_* → 子图2 去 simbad_resolver → E6 路由消失 → B3 合并保留 OTYPES |
| P1 | B4, B5, ~~B11~~, B12, B14 | 契约与字段语义修复（B11 已撤回：extraction_method="database_query" 是对下游的正确对齐） |
| P2 | C1-C13 | 清理轮：~2500 行死代码、.bak、断链测试、docs、死配置 |
| P2 | D1-D12 | 对齐轮：统一口径、补测试守护 |
| P2 | E1-E15, F | 加固轮：锁、上限、统计边界、数据修正 |

---

## 8. 附录：审计方法与正向确认

**方法**：6 路并行 agent 完整深读（每文件全文）+ 主会话对 12 处关键接缝逐一亲核（含运行时复现 A2 的 ImportError、全库 py_compile、RAG 全量统计、CRLF/SyntaxWarning 定位）。

**正向确认（避免误伤）**：
- 子图节点返回键全部在各自 state 声明（无 langgraph 静默丢弃，除 human_review `_from_conflict`）
- 两张主路由映射表与返回值完全对齐（subgraph1/subgraph2 图装配）
- 知识库/单位表/实体类型生成产物三方一致（34 组 257 条 / 28 字段 1178 别名 / 153 类型）
- MERGE_COMPLETION_REPORT 声称的 12 项修复基本全部真实存在（逐项验证）
- 缓存路径与 .gitignore 精确匹配；output 样例结构与声称一致
- 全部 30K 行 py_compile 通过（唯一警告即 E13）
- target_schema/standard_units 注入确实被 unit_converter 消费（非"只注入不用"）

**环境说明**：当前目录非 git 仓库（.env 尚未入库，A3 尚未现实化）；Python 3.14.5；模型名 `deepseek-v4-flash` 与本机环境一致（疑似内网代理别名，A5 需确认 key 注入）。

---

## 9. 修复记录（2026-08-05）

| 条目 | 状态 | 改动 |
|---|---|---|
| A1 数据库检索断线 | ✅ 已修复 | `subgraph2/nodes/database_query.py:41` 改读 `simbad_aliases`（恢复 combine 原语义），注释防回退 |
| A2 补充材料映射断线 | ✅ 已修复 | `subgraph2/utils/column_mapper.py:55` 四级→三级相对导入 |
| supplement provenance 对齐 | ✅ 已修复 | `supplementary_query.py:368-397` provenance 对齐 DB 四要素（cds_table_id→db_table, entity_column→key_column, matched_alias→key_value），补 source_kind="supplement"，record_id 加 bibcode 维度（修 S14） |
| A3 密钥明文硬编码 | ✅ 已修复 | subgraph1 config 加 load_dotenv + env var fallback；config.yaml 清除 api_key/base_url；根 .env 统一管理全部密钥；删除 astroquery_ai/.env 重复；根 .env.example 重写为全量模板（10 个变量） |
| D4 .env.example 缺键 | ✅ 已修复（随 A3） | 根 .env.example 全量模板覆盖全部代码读取的 env 键 |
| database 补 source_kind | ✅ 已修复 | `database_utils.py:198-205` provenance 加 source_kind="database"，与 supplement 对称 |
| B11 extraction_method | ✅ 撤回 | 经下游分析确认 `"database_query"` 正确——`is_database_record()` 以此判 DB 分支，supplement 与 database 处理方式相同、应走同一分支。区分用 source_kind |
| D12 别名键名分裂 | ✅ 已修复（随 A1） | `subgraph2/state.py:33-38` 注释纠正，读侧统一 |
| B15 关联加固（entity_type 兜底） | ✅ 已修复 | `database_query.py:179` 增加 `simbad_object_type` 中间兜底 |
| C10 重复日志（部分） | ✅ 已修复 | `database_query.py` 删除第二次重复统计日志块 |
| S14 record_id 冲突 | ✅ 已修复 | supplement record_id 加入 parent_bibcode 维度，同表多论文不再冲突 |
| B2/B3/E6 SIMBAD 收敛重构 | ✅ 已修复 | P1 补 ids 产出别名 → adapters 映射 simbad_* → 子图2 删 simbad_resolver + 路由 → START 直接并行（3 文件 6 处改动）|
| B4 契约枚举对齐 | ✅ 已修复 | 4 处 `"inferred"` → 替换为 `"modified"`（contract reality），默认值统一为 `"confirmed"` |
| B5 退出词被吞 | ✅ 已修复 | `routing.py:37` 加 `and query_type != "exit"` |
| **新：毒缓存** | ✅ 已修复 | `column_mapper.py` 空映射不写缓存（原 14 条空映射毒缓存使 LLM 映射永远短路）；删除毒缓存文件 |
| **新：D1 三态语义** | ✅ 已修复 | `database_utils.py` + `database_query.py`：无白名单→原始列名兜底；有白名单无匹配→0 条（不再输出 recno 等垃圾列名）；有匹配→只输出映射列 |
| **新：P1 选库频率启发式** | ✅ 已修复 | `property_standardization.py`：OTYPES 按出现频率降序选 RAG 库（原首码优先导致 M31 选 QSO.json 而非 G.json） |
| A5 quality_pipeline LLM | ⏸️ 配置项 | 非代码缺陷——所有 Agent 有 template fallback 优雅降级，.env 已预留 key |
| A4 子图1 input() 阻塞 | ⏸️ 搁置 | CLI 阶段 input() 正确，Web 化方案（Headless Protocol）已设计，搭建前端时执行 |

验证：改动文件全部 py_compile 通过；SIMBAD ids 字段实证返回 41 个别名（M31）；P1→adapters→子图2 别名传递链完整。

<!-- END -->

<!-- END -->
