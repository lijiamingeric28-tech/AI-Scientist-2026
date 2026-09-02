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
    """单篇源文献的元数据。"""

    source_id: str = Field(
        ...,
        description="源文献全局唯一标识。优先使用 DOI（如 10.xxx/xxx），"
        "若无 DOI 则使用内部 hash。",
        examples=["10.1016/j.msea.2023.145678"],
    )

    source_type: Literal["paper"] = Field(
        default="paper",
        description="源文献类型。V1 固定为 'paper'。",
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

    access_path: str = Field(
        ...,
        description="PDF 获取 URL 或本地缓存路径。",
    )

    retrieval_priority: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="检索子图分配的优先级评分，范围 [0, 1]。",
    )
