# Grounded Data Schema V2.0 最终规范文档

**版本**: 2.0.0  
**发布时间**: 2026-07-26  
**变更**: 合并V1.2与V2扩展计划，新增source层检索字段、record层提取上下文字段

---

## 一、顶层结构

```json
{
  "schema_version": "2.0.0",
  "sources": [...],
  "records": [...]
}
```

### 字段说明

| 字段               | 类型     | 必填  | 说明                     |
| ---------------- | ------ | --- | ---------------------- |
| `schema_version` | string | ✅   | Schema版本号，V2.0为"2.0.0" |
| `sources`        | array  | ✅   | 数据来源列表（论文、数据库等）        |
| `records`        | array  | ✅   | 提取的数据记录列表              |

---

## 二、Sources字段

### 2.1 Source类型分类

目前支持三种source_type：

- **paper**: 学术论文
- **database**: 数据库（待定，延后对接）
- **supplement**: 补充材料

---

### 2.2 Paper类型

#### 2.2.1 完整结构

```json
{
  "source_id": "W2280104906",
  "source_type": "paper",
  "doi": "10.1038/nature17140",
  "title": "A repeating fast radio burst",
  "authors": ["L. G. Spitler", "P. Scholz", "..."],
  "year": 2016,
  "journal": "Nature",
  "access_path": "./data/papers/W2280104906.pdf",
  "retrieval_priority": 0.4168,
  "abstract": "We report the discovery of a repeating fast radio burst...",
  "keywords": ["fast radio burst", "FRB", "radio transients"],
  "search_query": "repeating fast radio burst FRB detection",
  "search_rank": 3
}
```

#### 2.2.2 字段说明

| 字段                   | 类型     | 必填  | 说明                                          |
| -------------------- | ------ | --- | ------------------------------------------- |
| `source_id`          | string | ✅   | 唯一标识符（OpenAlex ID、arXiv ID等）                |
| `source_type`        | string | ✅   | 固定值："paper"                                 |
| `doi`                | string | ⚠️  | DOI（如果有）                                    |
| `title`              | string | ✅   | 论文标题                                        |
| `authors`            | array  | ✅   | 作者列表                                        |
| `year`               | number | ✅   | 发表年份                                        |
| `journal`            | string | ⚠️  | 期刊名（论文类型必填）                                 |
| `access_path`        | string | ✅   | 本地文件路径                                      |
| `retrieval_priority` | number | ⚠️  | 检索优先级（0-1）                                  |
| `abstract`           | string | ⚠️  | 论文摘要全文（子图2检索时从ADS/arXiv/Semantic Scholar获取） |
| `keywords`           | array  | ⚠️  | 作者关键词或数据库索引关键词                              |
| `search_query`       | string | ⚠️  | 子图2检索该文献时使用的查询字符串                           |
| `search_rank`        | number | ⚠️  | 在检索结果中的排名位置（1-based）                        |

**字段用途说明**：

- **abstract**: LLM理解论文研究目标、观测设备（FAST/VLA/Gaia/JWST）、数据来源、目标天体，是领域洞察的核心上下文
- **keywords**: 快速领域分类，辅助relationship_heuristics匹配
- **search_query**: 理解该文献与用户意图的关联，辅助相关性判断
- **search_rank**: 辅助retrieval_priority的可解释性，理解搜索质量

---

### 2.3 Database类型

```json
待定，可能需要1-2天后确定。继续延后对接。
```

---

### 2.4 Supplement类型

#### 2.4.1 完整结构

```json
{
  "source_id": "arXiv:1234.5678",
  "source_type": "supplement",
  "title": "Supplementary data for quasar observations",
  "parent_paper_id": "W2280104906",
  "filename": "data_table.csv",
  "access_path": "./data/supplements/1234.5678/data_table.csv"
}
```

#### 2.4.2 字段说明

| 字段                | 类型     | 必填  | 说明               |
| ----------------- | ------ | --- | ---------------- |
| `source_id`       | string | ✅   | 唯一标识符            |
| `source_type`     | string | ✅   | 固定值："supplement" |
| `title`           | string | ✅   | 补充材料标题           |
| `parent_paper_id` | string | ✅   | 关联的主论文source_id  |
| `filename`        | string | ✅   | 文件名              |
| `access_path`     | string | ✅   | 本地文件路径           |

---

## 三、Records字段

### 3.1 完整结构

```json
{
  "record_id": "W2280104906_FRB_150418_dispersion_measure_0",
  "source_id": "W2280104906",
  "entity_type": "FRB",
  "entity_name": "FRB 150418",
  "field_name": "dispersion_measure",
  "field_value": "776.2(5)",
  "field_unit": "cm^-3 pc",
  "trace_id": "doc0_p4",
  "provenance": {
    "page": 4,
    "bbox": [146, 1205, 1184, 1250]
  },
  "extraction_method": "vlm_text",
  "constraints": [
    {
      "name": "time_range",
      "status": "verified"
    },
    {
      "name": "dm_range",
      "status": "verified"
    }
  ],
  "extraction_confidence": 0.92,
  "context_snippet": "We observed FRB 121102 using FAST at L-band (1.0-1.5 GHz) with 128-μs time resolution. The measured DM is 776.2±0.5 pc cm⁻³...",
  "measurement_method": "radio interferometry",
  "condition_tags": ["L-band", "FAST", "high time resolution"]
}
```

### 3.2 字段说明

| 字段                      | 类型     | 必填  | 说明                                                              |
| ----------------------- | ------ | --- | --------------------------------------------------------------- |
| `record_id`             | string | ✅   | 唯一标识符                                                           |
| `source_id`             | string | ✅   | 关联到sources的source_id                                            |
| `entity_type`           | string | ⚠️  | 实体类型（FRB, Quasar, Galaxy, Pulsar, Exoplanet等）                   |
| `entity_name`           | string | ⚠️  | 实体名称（FRB 20180916B, 3C 273, M31等）                               |
| `field_name`            | string | ✅   | 字段名称（标准化后的）                                                     |
| `field_value`           | string | ✅   | 字段值                                                             |
| `field_unit`            | string | ⚠️  | 单位（如果有）                                                         |
| `trace_id`              | string | ✅   | 追踪ID                                                            |
| `provenance`            | object | ✅   | 溯源信息                                                            |
| `extraction_method`     | string | ✅   | 提取方法                                                            |
| `extraction_confidence` | number | ⚠️  | 提取模型对该条记录的置信度（0.0-1.0）                                          |
| `context_snippet`       | string | ⚠️  | 提取该值时的原文上下文（~200字符），包含观测设备、波段、数据处理方法等                           |
| `measurement_method`    | string | ⚠️  | 从上下文中识别出的观测方法/仪器（spectroscopy/photometry/radio interferometry等） |
| `condition_tags`        | array  | ⚠️  | 从上下文中提取的观测条件标签（L-band/C-band/X-ray/optical等）                    |

### 3.3 新增字段用途说明

#### extraction_confidence

- **用途**: LLM评估数据可靠性时的加权因子，低置信度记录在洞察中标注不确定性
- **来源**: 子图3提取时输出

#### context_snippet

- **用途**: LLM领域洞察的核心输入——从中解析望远镜/仪器、观测频段、光谱分辨率、数据处理pipeline等
- **来源**: 子图3提取时获取原文上下文
- **示例**: "We observed FRB 20180916B using FAST at L-band (1.0-1.5 GHz) with 128-μs time resolution. The measured DM is 349.8±0.3 pc cm⁻³, consistent with the NE2001 Galactic model..."

#### measurement_method

- **用途**: 跨来源差异分析——不同观测方法/仪器可能导致系统性偏差（如测光红移 vs 光谱红移）
- **来源**: 子图3从context_snippet中识别
- **常见值**: spectroscopy, photometry, radio interferometry, Gaia astrometry

#### condition_tags

- **用途**: 条件分组——同天体在不同波段/仪器下的观测值差异不是冲突而是多维度信息
- **来源**: 子图3从context_snippet中提取
- **示例**: ["L-band", "C-band", "X-ray", "optical", "低分辨率光谱", "高精度测光"]

---

### 3.4 Provenance字段

```json
同样，需要对数据库调研后确定数据库的溯源方法。继续延后对接。
```

---

### 3.5 Extraction Method

| 值             | 说明       |
| ------------- | -------- |
| `vlm_pdf`     | VLM从正文提取 |
| `database`    | 数据库查询    |
| `csv_parsing` | CSV文件解析  |
|               |          |
|               | ---      |

---

## 附录：版本变更历史

### V2.0.0 (2026-07-26)

- 合并V1.2规范与V2扩展计划
- Source层新增：abstract, keywords, search_query, search_rank
- Record层新增：extraction_confidence, context_snippet, measurement_method, condition_tags
- 明确三种source_type的结构差异

### V1.2.0 (2026-01-23)

- Record中添加constraints字段
- 扩展source_type为三种类型

### V1.0.0

- 初始版本
