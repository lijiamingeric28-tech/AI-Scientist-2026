"""
source.py

Source（源文献）Pydantic v2 模型。

对应 grounded_data.sources[] 中的每一项。
V1 仅支持 paper 类型，V2 将扩展 database / web。
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Source(BaseModel):
    """单篇源文献的元数据 — V2.0。"""

    source_id: str = Field(
        ...,
        description="源文献全局唯一标识。优先使用 OpenAlex ID、arXiv ID 等。",
        examples=["W2280104906"],
    )

    source_type: Literal["paper", "database", "supplement"] = Field(
        default="paper",
        description="源文献类型。V2.0: paper(论文), database(数据库), supplement(补充材料)。",
    )

    doi: Optional[str] = Field(
        default=None,
        description="DOI 标识符。若无法获取则为 None。",
    )

    title: str = Field(
        ...,
        description="文献标题。",
    )

    authors: list[str] = Field(
        default_factory=list,
        description="作者姓名列表。",
    )

    year: Optional[int] = Field(
        default=None,
        description="出版年份。",
    )

    journal: Optional[str] = Field(
        default=None,
        description="期刊或会议名称。",
    )

    access_path: Optional[str] = Field(
        default=None,
        description="PDF 获取 URL 或本地缓存路径。database 类型可为 None。",
    )

    retrieval_priority: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="检索子图分配的优先级评分，范围 [0, 1]。",
    )

    # ── V2.0: 检索上下文字段 (optional) ──
    abstract: Optional[str] = Field(
        default=None,
        description="论文摘要全文。V2.0 新增。",
    )

    keywords: Optional[list[str]] = Field(
        default=None,
        description="作者关键词或数据库索引关键词。V2.0 新增。",
    )

    search_query: Optional[str] = Field(
        default=None,
        description="检索该文献时使用的查询字符串。V2.0 新增。",
    )

    search_rank: Optional[int] = Field(
        default=None,
        description="在检索结果中的排名位置（1-based）。V2.0 新增。",
    )

    # ── V3.1: Database 类型字段 (optional) ──
    vizier_table_id: Optional[str] = Field(
        default=None,
        description="VizieR 或官方库中的标准 Table ID（如 I/355/gaiadr3）。",
    )

    description: Optional[str] = Field(
        default=None,
        description="数据库背景介绍、发布年份及总体定位。",
    )

    reference_paper: Optional[str] = Field(
        default=None,
        description="官方基准参考论文与期刊。",
    )

    bibcode: Optional[str] = Field(
        default=None,
        description="天文学 ADS Bibcode 标识符。",
    )

    research_methodology: Optional[str] = Field(
        default=None,
        description="探测器技术、数据归约方法、测光/天体测量原理。",
    )

    observation_facility: Optional[str] = Field(
        default=None,
        description="观测设施/卫星（如 Gaia Space Observatory）。",
    )

    waveband: Optional[str] = Field(
        default=None,
        description="工作波段及滤光片（如 Optical G/BP/RP）。",
    )

    research_content: Optional[str] = Field(
        default=None,
        description="包含的主要物理量及科学目标。",
    )
