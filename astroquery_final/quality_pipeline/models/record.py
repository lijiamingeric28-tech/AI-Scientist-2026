"""
record.py

Record（提取记录）与 Provenance（溯源锚点）Pydantic v2 模型。
"""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    """溯源锚点——描述数据在源文献或数据库中的物理位置。

    Paper 类型: 前端据此在原文 PDF 上高亮定位 (page + bbox)。
    Database 类型: 三坐标无损反向定位法 (db_table + key_column + key_value + raw_column)。
    """

    # Paper 溯源
    page: Optional[int] = Field(
        default=None,
        description="PDF 页码（1-based）。若无法确定则为 None。",
    )

    bbox: Optional[list[float]] = Field(
        default=None,
        min_length=4,
        max_length=4,
        description="边界框 [x0, y0, x1, y1]，0-1000 归一化坐标系（左上角原点）。"
        "前端按页面尺寸还原：x_px = x0/1000 * 页面宽。若无法确定则为 None。",
    )

    bbox_coord_system: Optional[str] = Field(
        default="normalized_1000",
        description="bbox 坐标系标注。当前统一为 'normalized_1000'（0-1000 归一化）。",
    )

    # V3.1: Database 溯源 (三坐标无损反向定位法)
    db_table: Optional[str] = Field(
        default=None,
        description="数据库/星表路径（如 I/355/gaiadr3）。",
    )

    key_column: Optional[str] = Field(
        default=None,
        description="数据库主键列名（如 Source, _2MASS, main_id）。",
    )

    key_value: Optional[str] = Field(
        default=None,
        description="数据库主键值（如 5854013331201520640）。",
    )

    raw_column: Optional[str] = Field(
        default=None,
        description="原始数据库列名（如 Plx, HG, B-V）。",
    )

    raw_unit: Optional[str] = Field(
        default=None,
        description="原始单位（上游保留，未换算）。用于溯源回查与单位换算留痕。",
    )

    standard_unit: Optional[str] = Field(
        default=None,
        description="该字段的标准单位（来自 PropertySpec）。",
    )

    # ── 补充材料 (supplement) 溯源 ──
    source_kind: Optional[str] = Field(
        default=None,
        description="来源种类，如 'supplement'。",
    )

    cds_table_id: Optional[str] = Field(
        default=None,
        description="CDS/VizieR 表 ID（如 J/MNRAS/427/1463）。补充材料专用。",
    )

    parent_bibcode: Optional[str] = Field(
        default=None,
        description="所属论文的 bibcode。补充材料专用。",
    )

    row_index: Optional[int] = Field(
        default=None,
        description="数据在原表中的行索引（从 0 开始）。",
    )

    matched_alias: Optional[str] = Field(
        default=None,
        description="行级过滤时命中的别名；'whole_table' 表示整表单天体表。",
    )


class Record(BaseModel):
    """单条数据提取记录 — V2.0。

    对应 grounded_data.records[] 中的每一项。
    V2.0 新增: entity_type, entity_name, extraction_confidence,
              context_snippet, measurement_method, condition_tags。
    """

    record_id: str = Field(
        ...,
        description="本条记录全局唯一标识。格式: {source_id}_{entity_name}_{field_name}_{n}。",
    )

    source_id: str = Field(
        ...,
        description="外键 → sources[].source_id。",
    )

    # ── V2.0: entity 字段 (optional) ──
    entity_type: Optional[str] = Field(
        default=None,
        description="实体类型（FRB, Quasar, Galaxy, Pulsar, Exoplanet等）。V2.0 新增。",
    )

    entity_name: Optional[str] = Field(
        default=None,
        description="实体名称（FRB 20180916B, 3C 273, M31等）。V2.0 新增。",
    )

    field_name: str = Field(
        ...,
        description="科学字段名，使用 snake_case（如 dispersion_measure）。",
    )

    field_value: Union[float, int, str] = Field(
        ...,
        description="提取值。number 或 string，不含 None。",
    )

    field_unit: Optional[str] = Field(
        default=None,
        description="单位（如 cm^-3 pc、Jy、K）。若字段无量纲则为 None。",
    )

    trace_id: Optional[str] = Field(
        default=None,
        description="溯源 ID，对应 hard_mapping_dict 的 key。"
        "格式: {doc_short_id}_p{page}。database 类型无 trace_id。",
    )

    provenance: Provenance = Field(
        default_factory=Provenance,
        description="物理溯源坐标（paper: page+bbox; database: db_table+key_column+key_value+raw_column）。",
    )

    extraction_method: Literal[
        "llm_text", "llm_table",
        "vlm_pdf", "vlm_text", "vlm_table", "vlm_figure",
        "database", "csv_parsing", "database_query"
    ] = Field(
        ...,
        description="提取方式。V3.1: database_query(数据库查询)。"
        "VLM 侧: 上游产出 f'vlm_{method}'，method 含 text/table/figure。",
    )

    # ── V2.0: 提取上下文与观测元数据 (optional) ──
    extraction_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="提取模型对该条记录的置信度（0.0-1.0）。V2.0 新增。",
    )

    context_snippet: Optional[str] = Field(
        default=None,
        description="提取该值时的原文上下文（~200字符），包含观测设备、波段等。V2.0 新增。",
    )

    measurement_method: Optional[str] = Field(
        default=None,
        description="从上下文中识别出的观测方法/仪器（spectroscopy/photometry/radio interferometry等）。V2.0 新增。",
    )

    condition_tags: Optional[list[str]] = Field(
        default=None,
        description="从上下文中提取的观测条件标签（L-band/C-band/X-ray/optical等）。V2.0 新增。",
    )
