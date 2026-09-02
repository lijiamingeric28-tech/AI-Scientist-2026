"""
论文元数据模型

用于存储从OpenAlex API获取的论文信息
"""

from pydantic import BaseModel, Field
from typing import Optional, List


class PaperMetadata(BaseModel):
    """
    论文元数据模型

    用于存储从OpenAlex API获取的论文信息
    """

    # ========== 核心标识字段 ==========
    id: str = Field(..., description="OpenAlex论文ID（如'W2741809807'）或PMID（如'PMID:12345678'）")
    doi: Optional[str] = Field(None, description="DOI，如'10.1016/j.actamat.2017.02.045'")

    # ========== PubMed专用字段 ==========
    pmid: Optional[str] = Field(None, description="PubMed ID")
    pmcid: Optional[str] = Field(None, description="PubMed Central ID")
    source_db: Optional[str] = Field(None, description="来源数据库：openalex/pubmed")
    pubmed_download_url: Optional[str] = Field(None, description="PubMed/PMC PDF链接")

    # ========== 基本信息字段 ==========
    title: str = Field(..., description="论文标题")
    abstract: Optional[str] = Field(None, description="论文摘要（从abstract_inverted_index重建）")

    # ========== 作者与出版信息 ==========
    authors: List[str] = Field(default_factory=list, description="作者姓名列表")
    year: Optional[int] = Field(None, description="发表年份")
    journal: Optional[str] = Field(None, description="期刊或会议名称")

    # ========== 引用与影响力 ==========
    citation_count: int = Field(0, description="被引次数")
    relevance_score: Optional[float] = Field(None, description="OpenAlex相关性得分（0-1）")

    # ========== 开放获取信息 ==========
    is_oa: bool = Field(False, description="是否开放获取")
    oa_url: Optional[str] = Field(None, description="开放获取链接")
    pdf_url: Optional[str] = Field(None, description="直接PDF链接")

    # ========== 主题与概念 ==========
    primary_topic: Optional[str] = Field(None, description="主题分类")
    concepts: List[str] = Field(default_factory=list, description="概念标签列表")

    # ========== Agent E添加的字段 ==========
    score: Optional[float] = Field(None, description="综合排序分数（Agent E计算）")

    # ========== Agent C添加的字段 ==========
    local_path: Optional[str] = Field(None, description="本地PDF文件路径")
    download_status: Optional[str] = Field(None, description="下载状态：success/failed/skipped")
    download_source: Optional[str] = Field(None, description="成功的下载源：pdf_url/oa_url/unpaywall/core")
    file_size: Optional[int] = Field(None, description="文件大小（字节）")

    class Config:
        # 允许字段动态添加（Agent C更新时）
        extra = "allow"
