# Normalization SubGraph 设计报告 V2.3

> **版本**: V2.3 — 并行执行 + LLM 动态 Tool 生成 + 安全沙箱
> **设计原则**: 一个 Stage = 一个 Node = 一个 Agent
> **核心创新**: LLM 根据数据问题自动编写/适配规范化工具函数 (3层架构), ThreadPoolExecutor 并行处理
> **对应文件**: `Data_Normalization_agentV1/normalization_graph.py` + `agents/*.py` + `tools/normalization/*.py`
> **更新 (2026-08-03, V4.2)**: 单位体系完整化 — unit_conversions_astrophysics 17 组 62 条 → 27 组 231 条（+flux_density/dispersion_measure/rotation_measure/frequency/energy/magnetic_field/pressure/density/angle/wavelength 10 组）、温度 °C/°F 偏移、3 处既有 bug 修复、target 非基准因子修正
> **更新 (2026-08-04, V4.3)**: VizieR 目录 schema 扩展 — 字段别名 349 → 1178（database_catalog_properties 919 + 标准字段 259，覆盖 23 个 VizieR 目录 1072 列，源自 vizier_catalogs_schema.json + query_results_progress_final.json）、单位组 27 → 34（+surface_brightness/abundance/wavenumber/surface_density/percentage/area/composite 7 组 + 4 组 VizieR 记法别名 solMass/solRad/solLum/log(cm.s**-2) 等）、semantic_types 7 键 units 同步 VizieR 记法、生成脚本 gen_catalog_schema.py（行级合并/幂等/备份回滚）

---

## 0. 变更记录 (V4.2 → V4.3)

### V4.3 (2026-08-04) — VizieR 目录 schema 扩展

| 变更 | 内容 |
|------|------|
| 字段别名扩展 | `target_schema_astrophysics` aliases 349 → **1178**: database_catalog_properties +919（23 个 VizieR 目录全量 1072 列中未覆盖部分, 无损保留防 Export 白名单丢弃）、标准字段 +259（BPmag/RPmag/W1mag→apparent_magnitude、Fnu_12/25/60/100/FG/FBP/FRP→flux_density、Teff→effective_temperature、logg→surface_gravity、[Fe/H]→metallicity、Mass/M500/MSZ→stellar_mass、Plx→parallax、pmRA/DE_pm→proper_motion、RV/Vbroad→radial_velocity、E(B-V)/A0→extinction 等） |
| 单位记法别名 | 4 组补 VizieR 标准记法键: mass.solMass / radius.solRad / luminosity.solLum+1e+37W / surface_gravity."log(cm.s**-2)"（含 1e+14solMass 系数前缀） |
| 新组 ×7 | surface_brightness（mag.arcsec**-2/MJy/sr）、abundance（Sun/log(Sun)）、wavenumber（um**-1）、surface_density（pc**-2/mas**-2）、percentage、area、composite（kpc/arcsec 等自转换） → 34 组 257 条 |
| semantic_types 同步 | stellar_mass/surface_gravity/metallicity/luminosity/density/wavelength 7 键 units 加入 VizieR 记法（solMass 单位字段可直接推断为 stellar_mass） |
| 生成脚本 | `scripts/gen_catalog_schema.py`: 读两份 JSON（vizier_catalogs_schema/query_results_progress_final）→ UCD+显式清单分类 → 行级合并（原别名+新别名, 不覆盖）、写前备份、写后 YAML 验证、失败自动回滚、幂等 |

### V4.2 (2026-08-03) — 单位体系完整化

| 变更 | 内容 |
|------|------|
| 转换规则扩展 | `unit_conversions_astrophysics` 17 组 62 条 → 27 组 231 条；新增 10 组: flux_density / dispersion_measure / rotation_measure / frequency / energy / magnetic_field / pressure / density / angle / wavelength（IAU 2015 B3 / CDS catstd / CODATA 2018 锚点, 乘法约定） |
| 温度偏移条目 | 温度组新增 `°C`/`℃`/`C` = "offset_-273.15"（°C→K）与 `°F`/`F` = "offset_32_5_9_273_15"（°F→K）；offset 因子走 `_apply_factor` 原路径 |
| 修复 1 | proper_motion 因子倒置: arcsec/yr 系列 0.001 → 1000（1 arcsec/yr = 1000 mas/yr, 基准 mas/yr=1.0） |
| 修复 2 | planet_radius / planet_mass 独立 unit_category — 原与恒星 radius/mass 组撞车: km 因子差 ~109×, kg 因子差 ~3.3e5× |
| 修复 3 | target 非基准因子修正（unit_converter.py）: `val × factor(unit) / factor(target)` — 先到组基准再换算到目标单位；此前只做 "→组基准" 单向换算却把 field_unit 替换为任意 target（如 5 G → "5.0 T" 静默错误） |

### V4 修复（随测随修, 已并入本报告）

| 修复 | 说明 |
|------|------|
| 乘法约定统一 | 全部转换因子统一为 `value_std = value × factor`（与 `_apply_factor` 及材料表 strength.GPa: 1000 一致）；原 distance/mass/radius/luminosity/planet 表的除法约定已换算修正 |
| 维度守卫 | target 单位必须属于 matched_cat 的规则集, 否则 `no_conversion_rule` — 防跨类误转（如 distance 字段的 'mag' 经 magnitude 规则转成 pc, 或无语义类型时 mag→pc fallback 误转） |
| 领域感知加载 | configs/__init__.py 增加 `_global_domain` 全局兜底（并行工作线程继承主线程领域, 否则天体物理域误载材料规则 → 单位转换全 0）; `load_domain_config` / `load_domain_schema_config` 按 `{section}_{domain}` → 通用段 → 默认段回退; unit_converter 按领域缓存 semantic→category 映射 |
| unconverted kinds | 拆分静默跳过 → 显式 unconverted: `missing_unit` / `no_target_unit` / `no_conversion_rule`; normalization_agent 汇入 errors, `has_unconverted_units` 真实化 |
| entity-aware 键 | semantic_types 键兼容 `"{et}:{en}/{field}"` 后缀匹配; 转换目标 entity_key 优先查找（V2 延续） |
| 空串单位 | 空串单位不再被忽略 — 视为缺失: missing_unit kind / Validation 缺失统计 / fill_default 填充（V4 fix: 空串也算缺失） |
| standard_units 回填 | quality_state.make_initial_state 从领域 target_schema 回填 `context_state.standard_units`（此前恒空 → 单位转换全部静默跳过） |

---

## 1. Agent 元信息

### 1.1 基本属性

| 属性 | 内容 |
|------|------|
| **Agent 名称** | Data Normalization Agent |
| **SubGraph 名称** | Data_Normalization_agentV1 |
| **所属子图** | SubGraph 4 (数据清洗与质检) |
| **版本** | V2.3（2026-08-03 更新 V4.2: 单位体系完整化） |
| **核心职责** | 根据 Quality Report 或 Conflict Report，对科学数据执行规范化处理，使数据符合目标 Schema |
| **关键约束** | **负责修改数据**，不负责判断数据质量或解决复杂冲突。Schema 完整性由 Assessment 负责。 |
| **修改数据** | ✅ 是 (唯一有权修改数据的 Agent) |

### 1.2 前后置条件

| 条件类型 | 条件 |
|---------|------|
| **前置条件** | `report_state.quality` 已被 Assessment 填充 |
|  | `report_state.quality.per_source_routes` 包含标记为 "Normalization" 的 sources |
|  | `data_state.current_data` 包含待处理数据 |
|  | 或 `report_state.conflict` 已被 Conflict/Variance 填充 (C→B 路径) |
| **后置条件** | `data_state.current_data` 已更新为规范化后的数据 |
|  | `report_state.normalization` 包含完整 Normalization Report |
|  | `workflow_state.route_decision` 已设置为 "Conflict" 或 "Export" |

### 1.3 在总图中的位置

```
AssessmentGraph → Dispatch → NormalizationGraph → LoopController → Export/Conflict
                                ↑                        ↓
                                └── ConflictGraph ←───────┘ (C→B 循环, 最多3次)
```

---

## 2. 架构概览 — 5 Stage 流水线

```
START → SourceRouterAgent → PlanningAgent → NormalizationAgent
      → ValidationAgent → ReportAgent → finalize → END

条件边:
  - SourceRouter: total_to_normalize==0 → finalize (V3.3 统一出口, 透传 execution_status 供主图 Gate)
  - Validation: Retry → 回退 PlanningAgent (Validation 内 MAX_NORM_RETRIES=1, V3.0; Graph 层守卫 retry_count<2)
```

---

## 3. Stage 1: SourceRouterAgent

**LLM**: 否 | **文件**: `agents/source_router_agent.py`

### 3.1 职责

读取 Assessment per-source 路由，筛选出需要规范化的 sources，区分触发来源。

### 3.2 处理流程

```
1. 读取 quality.per_source_routes → 筛选 route="Normalization" 的 sources
2. 读取 quality.conditional_routes → 获取每个 source 的 conditions 列表
3. 确定触发源:
   - report_state.conflict 存在 → trigger="conflict_report" (C→B 路径)
   - 否则 → trigger="quality_report" (A→B 路径)
4. 构建 sources_to_normalize:
   - record_count, conditions, needs_full_normalization, priority
   - V2: entities (per-entity breakdown, 来源 quality_scoring.per_entity_scores)
5. conflict_actions: 从 resolution_plan.actions_to_normalize 提取
   - V3.5 fix: 保留 record_ids / from_unit / to_unit (HumanReview 动作端到端落地)
   - 同时处理 annotations_to_add (retain_range/retain_both → conflict_annotations)
6. 无 source 需处理 → 直接 Export (route_decision="Export", execution_status="Success")
```

### 3.3 输出

```
report_state.normalization.source_plan = {
  trigger_source: "quality_report" | "conflict_report",
  sources_to_normalize: {sid: {record_count, conditions, entities, ...}},
  sources_skipped: [...],
  total_to_normalize, total_skipped
}
```

---

## 4. Stage 2: ToolPlanningAgent (LLM 驱动)

**LLM**: 是 (Layer 3 Custom Tool 生成) | **文件**: `agents/planning_agent.py`

### 4.1 3 层工具体系

```
┌─────────────────────────────────────────────────────┐
│  Layer 3: LLM-Generated Tools                       │
│  LLM 动态编写 Python 函数, sandbox 执行              │
│  安全约束: AST 白名单 + 禁危险函数 + Dry-run         │
│  触发条件: score >= 2 (V3.0: 减少不必要 LLM 调用)    │
├─────────────────────────────────────────────────────┤
│  Layer 2: Rule-Adapted Tools (V2.1)                 │
│  确定性规则为 Base Tool 注入自定义参数 (非 LLM)      │
│  例: schema_mapping + 别名规则                       │
│      unit_converter + 自动推断目标单位               │
│      missing_value_handler + 动态策略选择             │
├─────────────────────────────────────────────────────┤
│  Layer 1: Base Tools (6 个固定)                      │
│  schema_mapping / field_standardizer / unit_converter│
│  missing_value_handler / duplicate_handler           │
│  format_standardizer                                 │
└─────────────────────────────────────────────────────┘
```

### 4.2 Condition → Tool 映射

| Condition | Base Tool |
|-----------|----------|
| `alias_fields` | schema_mapping |
| `extra_fields` | schema_mapping |
| `format_issues` | field_standardizer |
| `unit_inconsistency` | unit_converter |
| `missing_units` | missing_value_handler |
| `missing_provenance` | missing_value_handler |
| `completeness_low` | missing_value_handler |
| `duplicate_records` | duplicate_handler |
| `general` | format_standardizer |

### 4.3 并行规划 (V2.3)

```
Step 1: 并行 Layer 1+2 (ThreadPoolExecutor, max 8 workers)
  - 每个 source 独立: 条件→Tool 映射 → Rule-Based Adaptations
  - V4 fix: _build_schema_std_unit_map 预构建标准单位映射 (context 优先, 领域配置兜底,
    含别名, 兼容 entity-aware key) — 此前依赖 infer_semantic_type 返回的 dict
    (无 standard_unit 键, 恒空) → adapted 单位参数恒空
  - 无 LLM, 纯确定性, 快速

Step 2: 并行 Layer 3 LLM (仅 needs_custom 的 source)
  - score >= 2 → 触发 LLM 生成 (V3.0: 减少不必要调用)
  - 每 source 最多 1 次 Layer 3 生成; 重试时回传上次失败错误信息给 LLM (V3.0)
  - V3.1: LLM 只写 business logic (预编译安全模板 _TOOL_CODE_TEMPLATE), 字段级统计
    profile 替代 5 条 sample; 3 条分层样本 (首/中/尾) dry-run 验证
  - V3.3 fix: dry-run 校验记录数一致 (工具只允许修改, 禁止增删记录)

Step 3: 汇总到 tool_registry.by_source
  - planning_method: "full_normalization" | "llm_enhanced" | "rule_engine"
```

### 4.4 Layer 3 触发条件 (V2.1 评分制)

```
_find_unresolved() 7 维度评分:
  维度1: 单位问题 (不一致/缺失) → +1
  维度2: 格式问题 → +1
  维度3: Schema 缺口 (extra/missing) → +1
  维度4: 溯源缺失 → +1
  维度5: 完整性不足 (score<0.85) → +1
  维度6: 跨来源冲突 → +1
  维度7: 复合问题 (>=2 维度同时存在) → +1

needs_custom = score >= 2  # V3.0: 至少 2 维度有问题才触发
```

### 4.5 Conflict Report 路径

```
trigger == "conflict_report" → 全量 Base Tools
  → 跳过 LLM 规划, 直接对所有 tools 执行
  → planning_method = "full_normalization"
```

---

## 5. Stage 3: NormalizationAgent (ToolExecutor)

**LLM**: 否 | **文件**: `agents/normalization_agent.py`

### 5.1 职责

按 tool_registry 分层执行: Layer 1 → Layer 2 → Layer 3。并行处理多个 source。

### 5.2 并行执行 (V2.3)

```
ThreadPoolExecutor (max 8 workers)
  每个 source 独立线程 (V3.1: 每 source 独立 sandbox, 防并发函数名覆盖):
    0. V3.5: 先执行 conflict_actions (human_replace / annotate / normalize_unit)
    1. Layer 1: 执行 base tools (V3.2: 传入 ctx — target_schema/standard_units/semantic_types)
    2. Layer 2: 执行 adapted tools (base + custom_params)
    3. Layer 3: 执行 generated tools (sandbox)
  汇总: modifications.base/adapted/generated + errors
  V4 fix: unit_converter 的 unconverted (missing_unit/no_target_unit/no_conversion_rule)
          汇入 errors — 此前被丢弃, quality_summary 的 has_unconverted_units 失真
  V3.2 fix: 工具 log → 逐记录 TraceEvent (record_id/field/before/after/tool/reason) 写入 data_trace
```

### 5.3 安全沙箱 (V2.1)

```
沙箱机制:
  1. AST 白名单: 50+ 允许的节点类型 (含 SetComp, GeneratorExp, USub)
  2. 模块白名单: math, re, json, copy, datetime, collections, itertools, ...
  3. 禁止函数: eval, exec, compile, open, getattr, __import__, __subclasses__, ...
  4. safe_builtins: 受限的 builtins (含 __import__ 允许 import 语句, AST 检查模块安全)
  5. 执行: compile(code, "<sandbox>", "exec") + exec(compiled, sandbox_globals)
  6. V3.1 fix: 每 source 独立 sandbox (_make_sandbox), 避免并发执行时函数名互相覆盖
```

### 5.4 Base Tools (6 个)

| # | Tool | 函数 | 功能 |
|---|------|------|------|
| T1 | schema_mapping | `map_to_target_schema()` | 别名→标准名映射 + V3.0 自动领域切换; V4 fix: catalog 原始列名保留 (`_raw_field`) |
| T2 | field_standardizer | `standardize_field_values()` | ~≈<>前缀清理 + ±不确定度处理 |
| T3 | unit_converter | `convert_units()` | 单位转换: (category, unit)→factor 乘法约定; offset 因子 (offset_273.15 K→°C / offset_-273.15 °C→K / offset_32_5_9 °F→°C / offset_32_5_9_273_15 °F→K); 维度守卫 (target 不在 matched_cat 组 → no_conversion_rule, 防 mag→pc); V4.2 target 非基准因子修正 (val × factor(unit) / factor(target)); 3 种显式 unconverted kind (missing_unit / no_target_unit / no_conversion_rule, 异常路径另计); 变体别名策略 (键精确匹配无归一化, 变体在配置中显式列全); 配置体系详见 5.6 |
| T4 | missing_value_handler | `handle_missing_values()` | 3策略: mark/drop/fill_default; V2.3 grounded_data 感知; V4 fix: 空串也算缺失 |
| T5 | duplicate_handler | `handle_duplicates()` | 精确去重 + 语义去重 (V1.1 entity 感知) + rejected过滤 |
| T6 | format_standardizer | `standardize_format()` | 数值去尾随零/字符串trim |

### 5.5 V2 Per-entity Tracking

```
每个 source 跟踪:
  - entities_in_source: 该 source 涉及的实体列表
  - per_entity_mods: {elabel: modification_count} 每个实体的修改次数
```

### 5.6 单位转换配置体系 (V4.2)

转换规则全部配置化, 代码零硬编码（除 offset_* 因子的运算语义）。

**1. `configs/schema_mapping.yaml` → `unit_conversions_astrophysics` (34 组 257 条)**

| 组 | 基准单位 | 要点 |
|----|---------|------|
| distance | pc | kpc/Mpc/Gpc/AU/ly/m/cm |
| mass | Msun | kg/g/M_jup/M_earth, M☉/M⊙ 变体 |
| radius | Rsun | cm/m/km/R_jup/R_earth |
| luminosity | erg/s | Lsun/W/"10^33 erg/s" |
| velocity | km/s | m/s/cm/s + "km s^-1" 变体 |
| proper_motion | mas/yr | V4.2 fix: arcsec/yr=1000（原 0.001 倒置） |
| period | d | hr/min/s/ms/yr (365.25 d) |
| age | Gyr | Myr/kyr/yr/Ga |
| magnitude | mag | 无量纲 |
| temperature | K | V4.2: °C/℃/C="offset_-273.15", °F/F="offset_32_5_9_273_15" |
| extinction | mag | 无量纲 |
| parallax | mas | arcsec=1000, μas=0.001 |
| metallicity | dex | 无量纲 |
| surface_gravity | dex | cm/s^2/m/s^2/gal/mGal |
| redshift | "" | 无量纲 |
| planet_radius | R_earth | V4.2 独立组: R_jup=11.209, km=1.5698e-4（原撞恒星 radius 组, 差 ~109×） |
| planet_mass | M_earth | V4.2 独立组: M_jup=317.8, kg=1.6744e-25（原撞恒星 mass 组, 差 ~3.3e5×） |
| flux_density | Jy | mJy/uJy/μJy/nJy/pJy + erg/s/cm^2/Hz 系列（V4.2 新增） |
| dispersion_measure | cm^-3 pc | V4.2 新增 |
| rotation_measure | rad/m^2 | V4.2 新增 |
| frequency | Hz | kHz/MHz/GHz/THz + s^-1 变体（V4.2 新增） |
| energy | erg | J/eV/keV/MeV/GeV/TeV/PeV/EeV（V4.2 新增） |
| magnetic_field | G | mG/uG/μG/nG/kG/T/mT/uT/nT（V4.2 新增） |
| pressure | Pa | kPa/MPa/GPa/bar/atm/dyn/cm^2/mmHg/torr（V4.2 新增） |
| density | g/cm^3 | kg/m^3/amu/cm^3（V4.2 新增） |
| angle | deg | arcmin/arcsec/mas/rad（V4.2 新增） |
| wavelength | nm | Å/um/μm/mm（V4.2 新增） |
| surface_brightness | mag.arcsec**-2 | mag/arcsec^2、MJy/sr（V4.3 新增, VizieR 记法） |
| abundance | Sun | log(Sun)（V4.3 新增, 丰度相对太阳） |
| wavenumber | um**-1 | 1/um（V4.3 新增, 波数） |
| surface_density | pc**-2 | mas**-2（V4.3 新增） |
| percentage | % | percent（V4.3 新增, 天体段） |
| area | arcmin**2 | 0.001arcmin**2（V4.3 新增） |
| composite | kpc/arcsec | 1e-15W.m**-2、log(yr)、pix、ct 等自转换（V4.3 新增） |

> V4.3 记法说明: VizieR 原始单位记法（solMass/solRad/solLum/Sun/** 指数/1e+X 前缀）作为**别名键**加入对应组,
> 与简化记法（Msun/Rsun/Lsun/^）并存 — unit_converter 键精确匹配, 两种记法均可转换。

**2. `configs/schema_mapping.yaml` → `target_schema_astrophysics` (28 字段)**

每字段定义 `standard_unit` + `aliases` + `semantic_type`, 是转换目标单位的唯一来源。
V4 fix: `quality_state.make_initial_state` 从该段回填 `context_state.standard_units`
（此前恒空 → 单位转换全部静默跳过）。

**3. `configs/quality_rules.yaml` → `semantic_types_astrophysics`**

`unit_category` 字段驱动 category 推断: `_load_semantic_category_map()` 按领域动态加载
（`semantic_types_{domain}` 优先, 通用段兜底, 内置 fallback 表最后）。
V4.2 fix: planet_radius / planet_mass 的 unit_category 独立（见上表）; 新增
catalog_metadata 规则（单字母关键词 'L'/'M' 子串误命中 luminosity/mass 的防误判）。

**4. `configs/__init__.py` — 领域感知加载**

- `load_domain_schema_config(section)`: `{section}_{domain}` → 通用段（schema_mapping.yaml）
- `load_domain_config(section, default)`: 三段回退（quality_rules.yaml）
- V4 fix: `_global_domain` 全局兜底 — ThreadPoolExecutor 工作线程无线程本地 domain 缓存,
  回退主线程领域; 否则天体物理域会误载材料规则（53 次 UnitConv 全 0 converted）

**因子约定与 key 策略**:

- 乘法约定: `value_std = value × factor`（V4 统一; offset_* 字符串例外, 走 `_apply_factor` 原路径）
- 键精确匹配: (category, unit) 二元组, 无归一化 — 变体（km/s vs km s^-1 vs km s⁻¹）在配置中显式列全
- V4.2: target 非基准因子修正 — `val × factor(unit) / factor(target)`（先到组基准, 再除 target 因子到目标单位）

---

## 6. Stage 4: ValidationAgent

**LLM**: 否 | **文件**: `agents/validation_agent.py`

### 6.1 职责

4 维校验: Schema / Format / Conflict / Semantic。V3.0: Schema 完整性检查已移除 (由 Assessment 负责)。

### 6.2 校验逻辑 (V3.0)

```
1. Schema: 只检查 critical 字段 (数据完整性由 Assessment 负责)
   still_missing = []  # V3.0: 不做 schema 完整性检查

2. Format: 统计缺失单位/溯源的记录数

3. Conflict: detect_conflicts_statistical() — 向后兼容

4. Semantic: infer_all_fields() → out_of_range 统计

V3.0 Retry 控制:
  - Layer 3 LLM 生成失败 → 非阻塞 warning, 不影响验证通过
  - 仅 Base/Adapted 工具问题触发 Retry (MAX_NORM_RETRIES=1)
  - Retry → 回退 PlanningAgent 重新规划

V4 fixes:
  - 空串单位也算缺失 (is_numeric 且 field_unit 为空/空串 → missing_units 统计)
  - route_decision 复检: needs_conflict → "Conflict" (B→C), 否则 "Export" —
    此前恒 Export, 冲突检测结果被主图 gate 覆写后完全丢失 (B→C 死代码)
  - conflict_check 保存完整结果 (conflicts/method=cohens_d/risk_level, V2.1 P1-2 fix)
```

### 6.3 Per-entity Validation (V2)

```
按 entity 分组:
  - records per entity
  - present_fields per entity
  - missing_units per entity
  - schema_ok (V3.0: always True)
  - format_ok
```

---

## 7. Stage 5: ReportAgent

**LLM**: 否 | **文件**: `agents/report_agent.py`

### 7.1 职责

汇总 modifications, 生成 Report, 设置 route_decision。

### 7.2 输出

```
report_state.normalization = {
  normalization_status: "Completed" | "Completed_With_Issues" | "Skipped_No_Sources",
  normalization_summary: "N sources processed, M modifications...",
  tool_registry_summary: {base_tools_used, adapted_tools_used, generated_tools_used},
  route_decision: "Conflict" | "Export",
  total_tool_calls,
  per_entity_modifications: {...}
}

route_decision:
  - validation.needs_conflict_analysis → "Conflict"
  - 否则 → "Export"
```

---

## 8. 重试策略 (V3.0)

| 层级 | 触发条件 | 动作 | 上限 |
|------|---------|------|------|
| Tool 执行 | 单个 Tool 失败 | catch → 记录 error → 继续 | — |
| Tool 生成 | LLM 代码/dry-run 失败 | 修正 → 重试 (回传错误信息) | 1 (V3.0) |
| Validation | Base/Adapted 工具问题 | 调整策略 → 重入 Planning | 1 (V3.0) |
| Layer 3 失败 | LLM 生成工具运行错误 | 非阻塞 warning → 继续 | — |
| Graph 层 | execution_status="Retry" | Router: 重入 NormalizationGraph | 3 |

---

## 9. State 读写

### 读取

| State 路径 | 用途 |
|-----------|------|
| `report_state.quality.sources[sid]` | per-source issues |
| `report_state.quality.per_source_routes` | 筛选 Normalization sources |
| `report_state.quality.conditional_routes` | per-source 条件修复指令 |
| `report_state.quality.profile.semantic_types` | 指导 unit_conversion |
| `report_state.quality.quality_scoring.per_entity_scores` | V2: per-entity breakdown (entities) |
| `report_state.conflict` | Conflict Report (C→B 触发全量规范化) |
| `data_state.current_data` | 待规范化数据 |
| `context_state.target_schema` | 目标 Schema (standard_unit 查询, V4: 领域配置兜底) |
| `context_state.standard_units` | V4: 从领域 target_schema 回填的目标单位 |

### 写入

| State 路径 | 写入者 | 内容 |
|-----------|--------|------|
| `data_state.current_data` | Stage 3 | 规范化后的数据 |
| `data_state.data_trace` | Stage 3 | V3.2: 逐记录 TraceEvent (record_id/field/before/after/tool/reason) |
| `report_state.normalization.source_plan` | Stage 1 | 来源分流结果 |
| `report_state.normalization.tool_registry` | Stage 2 | 工具注册表 (base/adapted/generated/by_source) |
| `report_state.normalization.planning_method` | Stage 2 | full_normalization / llm_enhanced / rule_engine |
| `report_state.normalization.modifications` | Stage 3 | 修改日志 (total/by_layer/details/per_source/errors/per_entity_modifications) |
| `report_state.normalization.validation` | Stage 4 | 校验结果 (conflict_check 完整数组) |
| `report_state.normalization.*` | Stage 5 | 完整 Report (normalization_status/summary/route_decision/total_tool_calls) |
| `workflow_state.route_decision` | Stage 4/5 | "Conflict" / "Export" |
| `workflow_state.tool_call_count` / `llm_call_count` | Stage 3/2 | 累计调用统计 |
| `workflow_state.workflow_history` | 各 Stage | 单条追加 (Reducer 按 dict 全等去重拼接) |

---

## 10. 异常处理

| 场景 | 处理 |
|------|------|
| 无 source 需规范化 | total_to_normalize=0 → finalize (V3.3 统一出口) → END (route=Export) |
| Conflict Report 触发 | 全量 Base Tools, 跳过 LLM 规划 (planning_method=full_normalization) |
| LLM 生成代码 AST 拒绝 | blocked → 返回 None → 跳过该 tool |
| LLM 生成代码质量低 | confidence 仅记录在 generated tool 元数据 (无 <0.7 阈值分支); 生成/编译/dry-run 失败 → 返回 None → 跳过 |
| 单位转换失败 | unconverted (missing_unit / no_target_unit / no_conversion_rule) 汇入 errors (V4 fix) — 供 quality_summary.has_unconverted_units 真实化 |
| Sandbox 执行失败 | catch → 记录 error → 继续其他工具 |
| Validation Retry 耗尽 | 强制进入 Report → route_decision = needs_conflict ? "Conflict" : "Export" (V4 fix) |

---

## 11. 文件清单

```
Data_Normalization_agentV1/
├── normalization_graph.py              # 138 行, 纯编排 (V2.1, 5 Agents + finalize)
├── NORMALIZATION_DESIGN_REPORT.md      # 本报告 (V2.3, 2026-08-03 更新 V4.2)
└── agents/
    ├── source_router_agent.py          # Stage 1: 筛选 + 分流
    ├── planning_agent.py               # Stage 2: LLM Tool Planning (核心)
    ├── normalization_agent.py          # Stage 3: Tool Executor + sandbox
    ├── validation_agent.py             # Stage 4: 4 维校验 + Retry
    └── report_agent.py                 # Stage 5: Report + 路由

tools/normalization/
├── schema_mapping.py                   # T1: Schema 映射 (V3.0 自动领域切换, V4 catalog _raw_field)
├── field_standardizer.py               # T2: 字段值标准化
├── unit_converter.py                   # T3: 单位转换 (category-keyed, V4.2 target 因子修正)
├── missing_value_handler.py            # T4: 缺失值处理
├── duplicate_handler.py                # T5: 去重
└── format_standardizer.py              # T6: 格式标准化

configs/                                # 单位转换配置体系 (详见 5.6)
├── schema_mapping.yaml                 # target_schema_astrophysics (28 字段, 1178 别名) + unit_conversions_astrophysics (34 组 257 条)
├── quality_rules.yaml                  # semantic_types_astrophysics (unit_category 驱动推断)
└── __init__.py                         # 领域感知加载 (V4: _global_domain 全局兜底)
```
