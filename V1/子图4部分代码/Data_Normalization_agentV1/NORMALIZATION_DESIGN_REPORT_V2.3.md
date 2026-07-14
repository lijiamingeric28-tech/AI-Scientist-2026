# Normalization SubGraph 设计报告 V2.3 — grounded_data 感知规范化

> **版本**: V2.3 — 面向 grounded_data 格式的精确规范化
> **核心变更**: Normalization 严格在 grounded_data 格式内工作，只修 field_name/field_value/field_unit，不动 trace_id/provenance/extraction_method。
> **对应文件**: `Data_Normalization_agentV1/normalization_graph.py` + `agents/*.py` + `tools/normalization/*.py`

---

## 1. 核心原则

### 1.1 数据契约

```
输入 (grounded_data)          输出 (grounded_data, cleaned)
┌─────────────────────┐       ┌─────────────────────┐
│ sources[]           │       │ sources[]           │  ← 不变
│   source_id, doi,   │  →    │   (原样保留)         │
│   title, authors... │       │                     │
├─────────────────────┤       ├─────────────────────┤
│ records[]           │       │ records[]           │
│   record_id         │       │   record_id         │  ← 不变
│   source_id         │       │   source_id         │  ← 不变
│   field_name  ✓修   │       │   field_name  ✓标准名│
│   field_value ✓修   │       │   field_value ✓干净值│
│   field_unit  ✓修   │       │   field_unit  ✓标准单位│
│   trace_id          │       │   trace_id          │  ← 不变
│   provenance        │       │   provenance        │  ← 不变
│   extraction_method │       │   extraction_method │  ← 不变
└─────────────────────┘       └─────────────────────┘
```

### 1.2 修改范围

| grounded_data 字段 | Normalization 能否修改 | 工具 |
|-------------------|----------------------|------|
| `record_id` | ❌ 不可修改 | — |
| `source_id` | ❌ 不可修改 | — |
| `field_name` | ✅ 别名→标准名 | schema_mapping |
| `field_value` | ✅ ~前缀清理/去重/类型转换 | field_standardizer, duplicate_handler |
| `field_unit` | ✅ 单位转换/补全 | unit_converter, missing_value_handler |
| `trace_id` | ❌ 不可修改 | — |
| `provenance` | ❌ 不可修改 | — |
| `extraction_method` | ❌ 不可修改 | — |

### 1.3 与 V2.0 的区别

| 维度 | V2.0 | V2.3 |
|------|------|------|
| 数据感知 | 泛化 "records" | 识别 grounded_data 各字段角色 |
| 修改范围 | 工具可能触碰任何字段 | 严格限制只修 field_name/value/unit |
| 保留字段 | 未明确 | trace_id/provenance/extraction_method 原样保留 |
| 去重逻辑 | 按 record_id 精确去重 | 按 record_id + (source_id, field_name, field_value) 语义去重 |
| 缺失值处理 | 只处理 field_unit 缺失 | 同时处理 field_unit 缺失 + trace_id 缺失标记 |

---

## 2. 5 Stage 修改详情

### 2.1 Stage 1: SourceRouterAgent (微调)

**原**: 读取 per_source_routes，筛选 Normalization sources
**改**: 增加 grounded_data 感知 — 从 records 中按 source_id 拆分时保留完整记录结构

无代码变更，但确保拆分时不丢失 trace_id / provenance。

### 2.2 Stage 2: ToolPlanningAgent (微调)

**原**: LLM 动态规划工具链 (Layer1+2+3)
**改**: 条件→工具映射增加 grounded_data 场景

新场景映射：
```python
_CONDITION_TOOL_MAP = {
    "alias_fields":       "schema_mapping",
    "format_issues":      "field_standardizer",
    "unit_inconsistency": "unit_converter",
    "unit_mismatch":      "unit_converter",
    "missing_units":      "missing_value_handler",
    "missing_provenance": "missing_value_handler",  # 标记但不修复
    "completeness_low":   "missing_value_handler",
    "duplicate_records":  "duplicate_handler",
    "general":            "format_standardizer",
}
```

注意: `missing_provenance` → `missing_value_handler` 只是标记，不修改 provenance 本身。

### 2.3 Stage 3: ToolExecutorAgent (核心修改)

**原**: 三层工具执行，工具可能修改任意 record 字段
**V2.3 关键约束**: 每个 Tool 执行后必须保留 grounded_data 特有字段

修改后的执行流程：
```
for each source:
  srecs = [完整 grounded_data records]

  Layer 1 Base:
    schema_mapping     → 只改 field_name
    field_standardizer → 只改 field_value
    unit_converter     → 只改 field_value + field_unit
    missing_value_handler → 只标记(不改 trace_id/provenance)
    duplicate_handler  → 按语义去重, 保留第一条的 trace_id
    format_standardizer → 只改 field_value 格式

  每个 Tool 执行后校验:
    - trace_id 仍然存在
    - provenance 未被修改
    - extraction_method 未被修改

  Layer 2 Adapted: 同 Base, 注入自定义参数
  Layer 3 Generated: 沙箱执行, 禁止修改 trace_id/provenance/extraction_method

  写回全局 records
```

### 2.4 Stage 4: ValidationAgent (微调)

**原**: 4 维校验
**改**: 增加 grounded_data 完整性校验

新增校验项:
- `trace_id_integrity`: 所有 record 的 trace_id 未被意外删除
- `provenance_integrity`: 所有 record 的 provenance 结构完整
- `extraction_method_integrity`: extraction_method 未被修改

### 2.5 Stage 5: ReportAgent (微调)

**原**: 汇总 + 路由
**改**: Report 中加入 grounded_data 修改统计

新增: `grounded_data_fields_preserved: true/false`

---

## 3. 工具修改详情

### 3.1 schema_mapping — 只映射 field_name

无变化。原本就只操作 `field_name`。

### 3.2 field_standardizer — 只清理 field_value

无变化。`~520` → `520`，类型转换 `str→float`。

### 3.3 unit_converter — 只改 value + unit

无变化。`0.438 GPa` → `438 MPa`。转换失败时标记 `unconverted`，不修改其他字段。

### 3.4 missing_value_handler — 只标记

**修改**: 策略为 `mark` 时，不修改任何字段，只在 record 上加 `_missing_unit: true` 标记（临时字段，Export 时移除）。

策略为 `drop` 时，删除整条 record（包括其 trace_id/provenance）。

### 3.5 duplicate_handler — 语义去重

**修改**: 
- 精确去重: 相同 `record_id` → 保留第一条
- 语义去重: 相同 `(source_id, field_name, field_value)` → 保留第一条（保留其 trace_id/provenance）
- 被去重的 record 的 trace_id 记录在 modification_log 中

### 3.6 format_standardizer — 只格式化

无变化。数值去尾随零、字符串 trim 等。

---

## 4. 新增: GroundedDataIntegrityGuard

每个 Tool 执行后的守卫检查：

```python
def guard_grounded_data_integrity(before: list[dict], after: list[dict]) -> dict:
    """
    校验 Tool 执行后未破坏 grounded_data 特有字段。
    """
    b_map = {r["record_id"]: r for r in before}
    a_map = {r["record_id"]: r for r in after}

    violations = []
    for rid, br in b_map.items():
        ar = a_map.get(rid)
        if not ar:
            continue
        for field in ("trace_id", "provenance", "extraction_method"):
            if br.get(field) != ar.get(field):
                violations.append({
                    "record_id": rid,
                    "field": field,
                    "before": str(br.get(field))[:50],
                    "after": str(ar.get(field))[:50],
                })

    return {
        "integrity_passed": len(violations) == 0,
        "violations": violations,
    }
```

---

## 5. 去重规则 (grounded_data 场景)

```
优先级:
  1. record_id 相同 → 精确重复 → 保留第一条
     场景: 提取子图生成了相同的 record_id

  2. (source_id, field_name, field_value) 完全相同 → 语义重复
     → 保留第一条, 删除后续
     场景: 同一来源同一字段提取了两次相同值

  3. extraction_method 不同但值相同 → 保留 llm_table 优先 (表格提取更可靠)
     场景: 同一数据从文字和表格各提取了一次

去重时保留的记录: 保留其 record_id, trace_id, provenance, extraction_method
去重时删除的记录: 其 trace_id 记录在 modification_log 中供溯源
```

---

## 6. 数据流示例

### 输入 (raw grounded_data)
```json
{
  "records": [
    {
      "record_id": "doi_A_yield_strength_1",
      "source_id": "doi_A",
      "field_name": "YS",              ← 别名
      "field_value": "~450",           ← 带前缀
      "field_unit": "MPa",
      "trace_id": "doc1_p3_tb2_r1",
      "provenance": {"page": 3, "bbox": [120, 340, 280, 355]},
      "extraction_method": "llm_table"
    }
  ]
}
```

### 经过 schema_mapping + field_standardizer 后
```json
{
  "records": [
    {
      "record_id": "doi_A_yield_strength_1",
      "source_id": "doi_A",
      "field_name": "yield_strength",  ← 已标准化
      "field_value": 450,              ← 已清理
      "field_unit": "MPa",
      "trace_id": "doc1_p3_tb2_r1",    ← 原样保留
      "provenance": {"page": 3, "bbox": [120, 340, 280, 355]},  ← 原样保留
      "extraction_method": "llm_table" ← 原样保留
    }
  ]
}
```

---

## 7. 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `tools/normalization/duplicate_handler.py` | 语义去重: 同 source+field+value → 保留一条 |
| `tools/normalization/missing_value_handler.py` | 只标记 _missing_unit, 不修改其他字段 |
| `Data_Normalization_agentV1/agents/normalization_agent.py` | 加入 GroundedDataIntegrityGuard |
| `Data_Normalization_agentV1/agents/validation_agent.py` | 加入 trace_id/provenance/extraction_method 完整性校验 |

---

## 8. 与其他模块的契约

### 输入
Normalization 接收 `data_state.current_data`，格式为 grounded_data。

### 输出
Normalization 产出 `data_state.current_data`，格式仍为 grounded_data，但：
- field_name 全为标准名
- field_value 全为干净数值
- field_unit 全为标准单位（或标记缺失）
- trace_id / provenance / extraction_method 原样保留
