"""
domain_config.py — Astronomy Domain Adapter (V3.5)

领域已确认为天文学 (astrophysics)。所有领域相关的硬编码常量集中于此,
Insights 各 Agent 从配置读取, 消除散落的硬编码。

若未来扩展多领域, 将本模块改为按领域键的配置映射 (domain_config[domain])。
"""
from __future__ import annotations

# ── 默认领域 ──
DEFAULT_DOMAIN = "astrophysics"

# ── 知识库 ──
from pathlib import Path
KNOWLEDGE_BASE_DIR = Path(__file__).parent.parent / "data" / "insight_knowledge"
KNOWLEDGE_DOMAIN = "astrophysics"               # 知识库子目录

# ── Insights 检索限制 ──
KB_TOP_K = 8               # 知识库检索 top_k
INSIGHT_BATCH_SIZE = 6     # V3.5: FieldInsight 字段分批大小 (prompt 过大时 LLM 覆盖骤降)
MAX_FIELD_SUMMARIES_CHARS = 12000   # field_summaries prompt 截断
MAX_SOURCE_SUMMARIES_CHARS = 6000   # source_summaries prompt 截断
MAX_INSIGHTS_CHARS = 10000          # field_insights prompt 截断
MAX_PAIRS_CHARS = 6000              # field_pairs prompt 截断
MAX_NARRATIVE_CHARS = 800           # overall_narrative 截断
MAX_KEY_OBSERVATIONS = 5            # synthesis 关键观测条数
MAX_FIELD_PAIRS = 30                # 关系字段对上限
MAX_LOW_CONF_RECORDS = 50           # low_confidence_records 上限
MAX_COVERAGE_GAPS = 30              # coverage_gaps 上限
MIN_RECORDS_FOR_RELATION = 2        # 关系检测最小记录数

# ── Insights 知识库检索类别 (按节点) ──
KB_CATEGORIES_FIELD_INSIGHT = [
    "physical_law", "empirical_relation", "measurement_principle",
    "reference_range", "galactic_model", "method_comparison",
]
KB_CATEGORIES_RELATIONSHIP = [
    "physical_law", "empirical_relation", "galactic_model",
    "cosmological_relation", "cosmological_model",
]
KB_CATEGORIES_RECOMMENDATION = [
    "methodology", "best_practice", "reference_range",
]

# ── 提取质量等确定性阈值 ──
EXTRACTION_QUALITY_HUMAN_THRESHOLD = 0.3   # Assessment 判 HumanReview 的提取质量阈值
COMPLETENESS_HUMAN_THRESHOLD = 0.5         # 完整度判 HumanReview 阈值
LOW_CONFIDENCE_THRESHOLD = 0.7             # Node 3 low_confidence 过滤阈值

# ── 实体类型 (Simbad otypes.list, V4) ──
ENTITY_TYPES_SECTION = "entity_types"      # quality_rules.yaml 段名
DEFAULT_ENTITY_TYPE = "galaxy"             # Unknown 推断兜底 (当前数据为河外)
ENTITY_TYPE_PARENT_SCORE = 2               # knowledge_store 父类匹配加分 (直接命中 +3)
