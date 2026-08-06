# 合并修复方案 · 实施细节

本文档是 `MERGE_PLAN.md` 的实施手册，包含每个修复项的具体改动位置、代码示例、测试验证方法。

---

## 实施顺序（按依赖关系）

```
C5 (包迁移) → 地基，其余全部依赖它
    ↓
C6 (cwd 路径) → 随 C5 一起修
    ↓
P1 节点 (PropertySpec) → 中枢，M1/M2/M3/M4/C4 依赖它
    ↓
┌────┬────┬────┬────┐
C1   M1   M2   M3   N4 (并行，互不依赖)
│    │    │    │    │
└────┴────┴────┴────┘
    ↓
M4/M5/M6/M7/C4 (聚合器改造)
    ↓
C2/N1/N5 (模型扩展)
    ↓
接缝适配器 + 主图挂接
    ↓
端到端测试
```

---

## C5：包迁移（91 文件 / 388 处导入）

### 步骤

1. **复制目录**（保留原目录作对照）
   ```bash
   cp -r "子图4部分代码" "combine/quality_pipeline"
   ```

2. **补 `__init__.py`**
   - 根目录：`combine/quality_pipeline/__init__.py`
   - `Data_Normalization_agentV1/__init__.py`
   - `Data_Assessment_agentV1/agents/__init__.py`
   - `Data_Conflict_agentV1/legacy/__init__.py`
   - `scripts/__init__.py`

3. **批量改写导入**（91 文件，13 个顶层模块名）
   
   需改写的模式（正则匹配）：
   ```python
   # 旧：from quality_state import QualityGraphState
   # 新：from quality_pipeline.quality_state import QualityGraphState
   
   # 旧：from utils.logger import get_logger
   # 新：from quality_pipeline.utils.logger import get_logger
   
   # 旧：from Data_Assessment_agentV1.assessment_graph import build_assessment_graph
   # 新：from quality_pipeline.Data_Assessment_agentV1.assessment_graph import ...
   ```
   
   13 个顶层模块名（按频率排序）：
   - `utils` (109 处)
   - `tools` (93 处)
   - `quality_state` (46 处)
   - `configs` (46 处)
   - `Data_Normalization_agentV1` (22 处)
   - `Data_Assessment_agentV1` (19 处)
   - `Data_Conflict_agentV1` (13 处)
   - `Data_Insights_agentV1` (11 处)
   - `Data_Export_agentV1` (9 处)
   - `models` (9 处)
   - `routers` (5 处)
   - `graph` (5 处)
   - `Data_HumanReview_agentV1` (1 处)

4. **脚本改写示例**
   ```python
   import os, re
   from pathlib import Path
   
   root = Path("combine/quality_pipeline")
   modules = ["quality_state", "configs", "models", "tools", "utils", 
              "routers", "graph", "Data_Assessment_agentV1", 
              "Data_Normalization_agentV1", "Data_Conflict_agentV1",
              "Data_Insights_agentV1", "Data_Export_agentV1",
              "Data_HumanReview_agentV1"]
   
   for pyfile in root.rglob("*.py"):
       if "__pycache__" in str(pyfile): continue
       src = pyfile.read_text(encoding="utf-8")
       modified = src
       for mod in modules:
           # from X import Y
           modified = re.sub(
               rf'^(\s*from\s+)({mod})([\s.]+)',
               rf'\1quality_pipeline.\2\3',
               modified, flags=re.MULTILINE
           )
           # import X
           modified = re.sub(
               rf'^(\s*import\s+)({mod})(\s|$)',
               rf'\1quality_pipeline.\2\3',
               modified, flags=re.MULTILINE
           )
       if modified != src:
           pyfile.write_text(modified, encoding="utf-8")
   ```

5. **逐文件 `py_compile` 验证**
   ```python
   import py_compile, sys
   errors = []
   for pyfile in Path("combine/quality_pipeline").rglob("*.py"):
       try:
           py_compile.compile(pyfile, doraise=True)
       except py_compile.PyCompileError as e:
           errors.append((pyfile, e))
   if errors:
       for f, e in errors[:10]:
           print(f"{f}: {e}")
       sys.exit(1)
   ```

### 验证
```python
# 能导入说明改写成功
from quality_pipeline.graph import build_quality_graph
from quality_pipeline.quality_state import QualityGraphState
```

---

## C6：修复 cwd 相对路径

### 改动位置

**`quality_pipeline/configs/domain_config.py`**
```python
# 旧
KNOWLEDGE_BASE_DIR = "data/insight_knowledge"

# 新
from pathlib import Path
KNOWLEDGE_BASE_DIR = Path(__file__).parent.parent / "data" / "insight_knowledge"
```

**`quality_pipeline/scripts/append_knowledge.py`**
```python
# 旧
KB_DIR = "data/insight_knowledge/astrophysics"

# 新
from pathlib import Path
KB_DIR = Path(__file__).parent.parent / "data" / "insight_knowledge" / "astrophysics"
```

### 验证
```python
from quality_pipeline.configs.domain_config import KNOWLEDGE_BASE_DIR
assert KNOWLEDGE_BASE_DIR.exists(), f"知识库路径不存在: {KNOWLEDGE_BASE_DIR}"
```

---

## P1：新增性质标准化节点

### 新文件：`combine/astroquery_ai/property_standardization.py`

```python
"""
P1 节点：性质标准化
输入：target_entity + raw_property_request
输出：PropertySpec (标准性质列表)
"""
from pathlib import Path
from astroquery.simbad import Simbad
import json

RAG_DIR = Path(__file__).parent.parent.parent / "train" / "rag_properties"

def resolve_entity(entity_name: str) -> dict:
    """SIMBAD 解析，取 main_id / otype / otypes / coords"""
    s = Simbad()
    s.add_votable_fields("otype", "otypes")
    result = s.query_object(entity_name)
    if not result:
        raise ValueError(f"SIMBAD 未找到: {entity_name}")
    row = result[0]
    return {
        "main_id": row["MAIN_ID"],
        "otype": row["OTYPE"],
        "otypes": row["OTYPES"].split("|") if row.get("OTYPES") else [],
        "ra": row["RA"],
        "dec": row["DEC"],
    }

def load_rag_for_otype(otype_list: list[str]) -> dict:
    """按 otypes → otype → _star.json 兜底选 RAG 文件"""
    candidates = otype_list + ["_star"]
    for ot in candidates:
        path = RAG_DIR / f"{ot}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"RAG 未找到任何候选: {candidates}")

def select_properties(rag_data: dict, user_request: str, llm_client) -> list[dict]:
    """LLM 从 RAG 性质列表里挑出用户要的"""
    props = rag_data.get("properties", [])
    prompt = f"""用户查询：{user_request}
可选性质（共 {len(props)} 个）：
{chr(10).join(f"- {p['property_id']}: {p.get('name_cn', '')} ({p.get('unit', '')})" for p in props)}

请选出用户需要的性质，输出 JSON 数组，每项只含 property_id。"""
    
    response = llm_client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    selected_ids = json.loads(response.choices[0].message.content).get("property_ids", [])
    return [p for p in props if p["property_id"] in selected_ids]

def standardize_properties(entity_name: str, user_request: str, llm_client) -> dict:
    """完整 P1 流程"""
    simbad = resolve_entity(entity_name)
    rag = load_rag_for_otype(simbad["otypes"] + [simbad["otype"]])
    property_spec = select_properties(rag, user_request, llm_client)
    return {
        "simbad_info": simbad,
        "otype_used": rag["otype"],
        "property_spec": property_spec,
    }
```

### 主图集成：`combine/astroquery_ai/graph.py`

```python
from .property_standardization import standardize_properties

def property_standardization_node(state: MainGraphState):
    """P1: 性质标准化"""
    result = standardize_properties(
        state["target_entity"],
        state["raw_property_request"],
        state["llm_client"]
    )
    return {
        "simbad_info": result["simbad_info"],
        "property_spec": result["property_spec"],
    }

# 在 build_graph() 里挂接
graph.add_node("property_standardization", property_standardization_node)
graph.add_edge("node1_澄清", "property_standardization")
graph.add_edge("property_standardization", "subgraph2_检索")
```

---

## M1：数据库列名归一

### 改动位置：`combine/astroquery_ai/subgraph2/database_query.py`

新增函数 `map_columns_to_properties`（LLM 判列名→property_id，按表缓存）：

```python
import hashlib, json, httpx, asyncio
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "column_mapping_cache"
CACHE_DIR.mkdir(exist_ok=True)

async def map_columns_to_properties(
    table_name: str,
    columns: list[dict],  # [{name, unit, ucd, description}, ...]
    property_spec: list[dict],
    llm_client,
) -> dict[str, str | None]:
    """
    LLM 判定 VizieR 列 → PropertySpec 的映射
    
    返回：{列名: property_id | None}
    缓存键：(table_name, PropertySpec 指纹)
    """
    # 缓存键
    spec_ids = sorted(p["property_id"] for p in property_spec)
    cache_key = f"{table_name}_{hashlib.md5(json.dumps(spec_ids).encode()).hexdigest()[:8]}.json"
    cache_path = CACHE_DIR / cache_key
    
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    
    # LLM 判定
    cols_desc = "\n".join(
        f"- {c['name']} | unit={c.get('unit')} | ucd={c.get('ucd')} | {c.get('description','')[:100]}"
        for c in columns
    )
    props_desc = "\n".join(
        f"- {p['property_id']} | {p.get('name_cn','')} | unit={p['unit']} | ucd={p.get('ucd','')}"
        for p in property_spec
    )
    
    prompt = f"""VizieR 表 {table_name} 有以下列：
{cols_desc}

目标性质（只能从中选择）：
{props_desc}

请为每个列判定它对应哪个目标性质（或 null 表示无匹配）。
输出 JSON: {{"mappings": [{{"column": "列名", "property_id": "xxx" | null, "reason": "..."}}, ...]}}"""
    
    response = await llm_client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    data = json.loads(response.choices[0].message.content)
    mapping = {m["column"]: m["property_id"] for m in data.get("mappings", [])}
    
    # 落盘
    cache_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    return mapping
```

修改 `build_database_records`：

```python
async def build_database_records(table, source_id, property_spec, llm_client):
    """
    ...
    新增参数：property_spec
    """
    # 获取列映射
    columns_meta = [
        {"name": col.name, "unit": col.unit, "ucd": col.ucd, "description": col.description}
        for col in table.columns
    ]
    mapping = await map_columns_to_properties(
        table.meta.get("name", "unknown"),
        columns_meta,
        property_spec,
        llm_client
    )
    
    records = []
    for row_idx, row in enumerate(table):
        for col in table.colnames:
            property_id = mapping.get(col)
            if not property_id:
                continue  # 无映射的列丢弃
            
            records.append({
                "record_id": f"REC_{source_id}_{row_idx}_{property_id}",  # 修复 C1
                "field_name": property_id,  # 标准名
                "field_value": str(row[col]),
                "field_unit": str(table[col].unit) if table[col].unit else "",  # 原始单位
                "provenance": {
                    "raw_column": col,
                    "raw_ucd": table[col].ucd,
                    "raw_unit": str(table[col].unit),
                    "llm_mapping_reason": "...",  # 从 LLM 响应取
                },
                # ...
            })
    return records
```

---

## M2/M3：VLM 与补充材料归一

### VLM prompt 注入白名单

**`combine/astroquery_ai/subgraph3/vlm_extraction.py`**

```python
def build_vlm_prompt(property_spec: list[dict], ...):
    whitelist = "\n".join(
        f"- {p['property_id']}: {p.get('name_cn','')} (单位: {p['unit']})"
        for p in property_spec
    )
    prompt = f"""从论文中提取以下性质的数据：
{whitelist}

**重要约束**：输出的 field_name 必须严格使用上述列表中的 property_id，不得自造名称。

输出 JSON: {{"records": [{{"field_name": "...", "field_value": "...", ...}}]}}"""
    return prompt
```

### 后置校验

```python
def validate_vlm_output(records: list[dict], property_spec: list[dict]) -> list[dict]:
    """丢弃 field_name 不在白名单内的记录"""
    valid_ids = {p["property_id"] for p in property_spec}
    filtered = []
    rejected = []
    for r in records:
        if r["field_name"] in valid_ids:
            filtered.append(r)
        else:
            rejected.append(r)
    if rejected:
        logger.warning(f"VLM 输出越界，已丢弃 {len(rejected)} 条: {[r['field_name'] for r in rejected[:5]]}")
    return filtered
```

### 补充材料

**`combine/astroquery_ai/subgraph2/supplementary_query.py`**

```python
def _llm_judge_table(table_meta: dict, property_spec: list[dict], ...):
    """
    ...
    新增参数 property_spec
    prompt 里注入：standard_name 只能从 property_spec 选
    """
    props_desc = ", ".join(p["property_id"] for p in property_spec)
    prompt = f"""...
可选的标准性质名（只能从中选择）：{props_desc}

输出的 property_columns 里每项的 standard_name 必须是上述之一，或 null。"""
    # ...
```

---

## C1/C2/C4/M4-M7/N1-N5：模型与聚合器改造

### C1：修复 record_id 重复

**`combine/astroquery_ai/subgraph2/result_builder.py:120`**
```python
# 旧
record_id = f"REC_{source_id}_{obj_id}_{col}"
# 新
record_id = f"REC_{source_id}_{obj_id}_{row_idx}_{col}"
```

### C2：扩 extraction_method Literal

**`combine/quality_pipeline/models/schemas.py`**
```python
class Record(BaseModel):
    extraction_method: Literal[
        "database_query", "vlm_pdf", "vlm_text",
        "vlm_table", "vlm_figure"  # 新增
    ]
```

### C4/M4/M5/M6/M7：聚合器

**`combine/astroquery_ai/aggregation.py`**
```python
def aggregate_results(...):
    # 新增字段
    output = {
        "research_domain": "astrophysics",  # C4
        "simbad_info": state.get("simbad_info"),  # M5
        "error_log": state.get("error_log", []),  # M4
        "processing_summary": state.get("processing_summary", {}),  # M4
        "sources": align_sources(all_sources),  # M6
        "records": all_records,
    }
    return output

def align_sources(sources: list[dict]) -> list[dict]:
    """M6: 三类 source 对齐到字段超集"""
    schema = {
        # 公共
        "source_id", "bibcode", "title", "authors", "year", "journal",
        # database 专有
        "catalog_name", "waveband", "observation_facility", "research_methodology",
        # paper 专有
        "retrieval_priority", "search_rank", "ads_link",
        # supplementary 专有
        "source_kind", "cds_table_id", "parent_bibcode",
    }
    return [{k: s.get(k) for k in schema} for s in sources]
```

**M7：补充材料 records 指向正确 source**
```python
# 在 build_supplementary_records 里
record["source_id"] = supplementary_source_id  # 而非 parent_bibcode
```

### N1：bbox 坐标系

**`combine/quality_pipeline/models/schemas.py`**
```python
class Provenance(BaseModel):
    bbox: list[float] | None = Field(
        default=None,
        description="边界框坐标（0-1000 归一化坐标系，左上角为原点）"  # 改描述
    )
    bbox_coord_system: str | None = Field(default="normalized_1000")  # 新增
```

### N5：Provenance 扩展字段

```python
class Provenance(BaseModel):
    # 新增（补充材料专用）
    source_kind: str | None = None
    cds_table_id: str | None = None
    parent_bibcode: str | None = None
    row_index: int | None = None
    matched_alias: str | None = None
```

---

## 接缝适配器 + 主图挂接

### 适配器：`combine/astroquery_ai/quality_adapter.py`

```python
"""接缝适配器：PropertySpec → quality_pipeline 的 context_state"""

def build_context_state(property_spec: list[dict], research_domain: str = "astrophysics") -> dict:
    """生成子图 4 的 context_state"""
    target_schema = {
        "schema_version": "1.0",
        "fields": [
            {
                "name": p["property_id"],
                "standard_unit": p["unit"],
                "semantic_type": infer_semantic_type(p),  # 从 category/ucd 推断
                "criticality": "optional",
            }
            for p in property_spec
        ]
    }
    standard_units = {p["property_id"]: p["unit"] for p in property_spec}
    
    return {
        "research_domain": research_domain,
        "target_schema": target_schema,
        "standard_units": standard_units,
    }

def infer_semantic_type(prop: dict) -> str:
    """从 RAG 性质的 category/ucd 推断 semantic_type（映射到 32 个语义类之一）"""
    # 简化版：按 category 粗映射
    mapping = {
        "physical": "metallicity",  # 默认物理量
        "photometric": "apparent_magnitude",
        "astrometric": "parallax",
        "kinematic": "radial_velocity",
        # ... 32 个语义类的完整映射
    }
    return mapping.get(prop.get("category"), "other")
```

### 主图挂接：`combine/astroquery_ai/graph.py`

```python
from quality_pipeline.graph import build_quality_graph
from .quality_adapter import build_context_state

def quality_node(state: MainGraphState):
    """P5: 质量管线"""
    grounded_data = state["final_output"]
    context = build_context_state(state["property_spec"], "astrophysics")
    
    # 注入 context 并调用子图 4
    quality_graph = build_quality_graph()
    result = quality_graph.invoke({
        "grounded_data": grounded_data,
        **context
    })
    return {"quality_report": result}

# 挂接
graph.add_node("quality", quality_node)
graph.add_edge("aggregation", "quality")
graph.set_finish_point("quality")
```

---

## 验证清单

### 单元测试
- [ ] 包导入：`from quality_pipeline.graph import build_quality_graph`
- [ ] 知识库路径：`KNOWLEDGE_BASE_DIR.exists()`
- [ ] PropertySpec 生成：给定 otype + 用户请求 → 返回标准性质列表
- [ ] 列名映射：给定 VizieR 表元数据 + PropertySpec → 返回列→property_id 映射
- [ ] VLM 白名单：prompt 包含 property_id 列表
- [ ] VLM 后置校验：越界 field_name 被丢弃

### 端到端
- [ ] 用户输入"M31 的铁丰度和 G 波段星等" → records 的 field_name = `fe_h` / `g_mag`
- [ ] research_domain 正确传递 → 子图 4 加载 `_astrophysics` 配置段
- [ ] 单位换算日志完整：原始单位 → 标准单位，因子正确
- [ ] Insights 能读到 simbad_info / error_log
- [ ] 补充材料 records 指向 supplementary_sources

### 回归
- [ ] 原 `子图4部分代码` 下的测试用例在迁移后仍通过
- [ ] record_id 唯一性：多行表不再抛 ValueError
- [ ] extraction_method 不再抛 ValidationError

---

## 删减清单（跑通后执行）

### 立即可删
- `子图4部分代码/tools/conflict/` 下 8 个工具（已注明未被调用）
- `子图4部分代码/Data_Conflict_agentV1/legacy/resolution_reasoning_agent.py`
- `quality_rules.yaml` / `schema_mapping.yaml` 里材料科学配置段（28 字段 + 8 单位组）

### 待验证后删减
- `target_schema` 的 1178 别名（保留少量常见别名作兜底）
- `entity_type` 三层推断链（只留 normalize）
- `llm_completeness` 猜缺失字段（降级为兜底）

---

**文档版本**：v1.0  
**创建时间**：2026-08-05  
**状态**：待实施
