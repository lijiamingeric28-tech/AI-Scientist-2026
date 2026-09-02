"""
常量定义

包含检索子图和意图澄清子图的所有配置常量
"""

import os

# ========== 功能开关 ==========

# 🔒 PubMed功能开关（全局控制）
ENABLE_PUBMED = False  # True=启用PubMed, False=禁用PubMed

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

# 从openalex_config导入配置
try:
    from configs.openalex_config import OPENALEX_EMAIL as _EMAIL, OPENALEX_API_KEY as _API_KEY
    OPENALEX_EMAIL = _EMAIL
    OPENALEX_API_KEY = _API_KEY
except ImportError:
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
OUTPUT_TOP_N = None  # None表示下载所有过滤后的论文（之前是25）

# ========== 论文下载 ==========
DOWNLOAD_DIR = "./data/papers"
DOWNLOAD_TIMEOUT = 45                      # 增加超时（从30→45秒）
DOWNLOAD_MAX_RETRIES = 2
DOWNLOAD_MAX_CONCURRENT = 15               # 提高并发（从3→15）
DOWNLOAD_RATE_LIMIT_PER_DOMAIN = 5        # 新增：每域名最大并发
DOWNLOAD_CONNECTION_POOL_SIZE = 20        # 新增：HTTP连接池大小
MIN_FILE_SIZE = 10 * 1024                 # 10KB
MAX_FILE_SIZE = 50 * 1024 * 1024          # 50MB

# 下载增强功能
DOWNLOAD_SHOW_PROGRESS = True             # 显示进度条
DOWNLOAD_ENABLE_STATS = True              # 启用统计

# ========== PubMed配置 ==========
PUBMED_EMAIL = os.getenv("PUBMED_EMAIL", "your_email@example.com")  # NCBI要求提供邮箱
PUBMED_API_KEY = os.getenv("PUBMED_API_KEY", "")  # 可选，有API Key可提高限速
PUBMED_MAX_RESULTS = 50  # 单次检索最大返回数
PUBMED_REQUEST_DELAY = 0.34  # 无API Key限速：3次/秒，有Key：10次/秒

# ========== PubMed下载配置 ==========
PUBMED_DOWNLOAD_FORMATS = ["pdf", "xml", "txt"]  # 下载格式优先级
PUBMED_DOWNLOAD_TIMEOUT = 60  # PubMed下载超时（秒）

# ========== Unpaywall/CORE配置 ==========
UNPAYWALL_EMAIL = "lijiamingeric28@gmail.com"  # 直接设置，不使用环境变量
CORE_API_KEY = os.getenv("CORE_API_KEY", "")

# ========== 通用配置 ==========
DEFAULT_DOMAIN = "materials_science"
