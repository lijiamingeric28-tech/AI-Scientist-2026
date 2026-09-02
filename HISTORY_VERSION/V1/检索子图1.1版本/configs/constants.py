"""
常量定义

包含检索子图和意图澄清子图的所有配置常量
"""

import os

# ========== 意图澄清子图配置 ==========

# 默认槽位Schema（generate_schema失败时使用）
DEFAULT_SCHEMA = {
    "entities": {
        "required": True,
        "description": "目标实体（材料、天体、化合物等）",
        "examples": [],
        "filled": False
    },
    "properties": {
        "required": True,
        "description": "目标属性（力学性能、物理常数等）",
        "examples": [],
        "filled": False
    },
    "conditions": {
        "required": False,
        "description": "约束条件（温度范围、时间范围、实验类型等）",
        "examples": [],
        "filled": False
    }
}

# 最大追问轮次
MAX_CLARIFICATION_TURNS = 3

# ========== LLM配置 ==========

# 模型选择
DEFAULT_MODEL = "qwen3.7-plus"
FAST_MODEL = "qwen-turbo"    # 用于简单任务
SMART_MODEL = "qwen-max"     # 用于复杂推理

# 超时配置
DEFAULT_TIMEOUT = 60  # 秒
LONG_TIMEOUT = 120     # 复杂任务

# 温度配置
LOW_TEMP = 0.1    # 确定性任务（如格式化、解析）
MID_TEMP = 0.5    # 平衡任务（如提取、推理）
HIGH_TEMP = 0.9   # 创意任务（如生成变体）

# ========== OpenAlex API配置 ==========
OPENALEX_BASE_URL = "https://api.openalex.org/works"
OPENALEX_TIMEOUT = 30
OPENALEX_MAX_RETRIES = 2
OPENALEX_EMAIL = os.getenv("OPENALEX_EMAIL", "your-email@example.com")
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "")

# ========== 查询扩展 ==========
MAX_SYNONYM_EXPANSIONS = 5
RETRIEVAL_DEFAULT_YEAR_RANGE = 50  # 默认年份范围

# ========== 文献搜索 ==========
SEARCH_PER_PAGE = 50

# ========== 引用链扩展 ==========
MAX_SEED_PAPERS = 5
MAX_CITED_BY_PER_SEED = 10
MAX_REFERENCES_PER_SEED = 10
CITATION_MIN_CITATION_COUNT = 3
CITATION_API_TIMEOUT = 30
CITATION_API_MAX_RETRIES = 2

# ========== 过滤与排序 ==========
FILTER_MIN_CITATION_COUNT = 3
FILTER_YEAR_RELAXATION = 2
FILTER_OA_HIGH_CITATION_THRESHOLD = 50
RANK_CITATION_WEIGHT = 0.4
RANK_RECENCY_WEIGHT = 0.3
RANK_RELEVANCE_WEIGHT = 0.3
OUTPUT_TOP_N = 25

# ========== 论文下载 ==========
DOWNLOAD_DIR = "./data/papers"
DOWNLOAD_TIMEOUT = 30
DOWNLOAD_MAX_RETRIES = 2
DOWNLOAD_MAX_CONCURRENT = 3
MIN_FILE_SIZE = 10 * 1024        # 10KB
MAX_FILE_SIZE = 50 * 1024 * 1024 # 50MB

# ========== Unpaywall/CORE配置 ==========
UNPAYWALL_EMAIL = os.getenv("UNPAYWALL_EMAIL", "your-email@example.com")
CORE_API_KEY = os.getenv("CORE_API_KEY", "")

# ========== 通用配置 ==========
DEFAULT_DOMAIN = "materials_science"
