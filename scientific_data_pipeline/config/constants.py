"""
常量定义

包含意图澄清子图和检索子图的所有配置常量
"""

import os

# ========== 功能开关 ==========

# 🔒 PubMed功能开关（全局控制）
ENABLE_PUBMED = False  # True=启用PubMed, False=禁用PubMed

# 🔗 引用扩展功能开关（全局控制）
ENABLE_CITATION_EXPANSION = False  # True=启用引用扩展, False=禁用引用扩展（加快速度）

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

# 模型选择（可通过环境变量覆盖）
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen3.7-plus")
FAST_MODEL = os.getenv("FAST_MODEL", "qwen-turbo")    # 用于简单任务
SMART_MODEL = os.getenv("SMART_MODEL", "qwen-max")     # 用于复杂推理

# 超时配置
DEFAULT_TIMEOUT = 60  # 秒
LONG_TIMEOUT = 120     # 复杂任务

# 温度配置
LOW_TEMP = 0.1    # 确定性任务（如格式化、解析）
MID_TEMP = 0.5    # 平衡任务（如提取、推理）
HIGH_TEMP = 0.9   # 创意任务（如生成变体）

# ========== 通用配置 ==========
DEFAULT_DOMAIN = "materials_science"

# ==========================================
# 检索子图配置（子图2）
# ==========================================

# ========== OpenAlex API配置 ==========
OPENALEX_BASE_URL = "https://api.openalex.org/works"
OPENALEX_TIMEOUT = 30
OPENALEX_MAX_RETRIES = 2

# API认证信息（从环境变量读取）
OPENALEX_EMAIL = os.getenv("OPENALEX_EMAIL", "your-email@example.com")
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "")

# ========== 查询扩展配置 ==========
MAX_SYNONYM_EXPANSIONS = 5
RETRIEVAL_DEFAULT_YEAR_RANGE = 50  # 默认年份范围

# ========== 文献搜索配置 ==========
SEARCH_PER_PAGE = 50

# ========== 引用链扩展配置 ==========
MAX_SEED_PAPERS = 5
MAX_CITED_BY_PER_SEED = 10
MAX_REFERENCES_PER_SEED = 10
CITATION_MIN_CITATION_COUNT = 3
CITATION_API_TIMEOUT = 30
CITATION_API_MAX_RETRIES = 2

# ========== 过滤与排序配置 ==========
FILTER_MIN_CITATION_COUNT = 3
FILTER_YEAR_RELAXATION = 2
FILTER_OA_HIGH_CITATION_THRESHOLD = 50
RANK_CITATION_WEIGHT = 0.4
RANK_RECENCY_WEIGHT = 0.3
RANK_RELEVANCE_WEIGHT = 0.3
OUTPUT_TOP_N = None  # None表示下载所有过滤后的论文

# ========== 论文下载配置 ==========
DOWNLOAD_DIR = "./data/papers"
DOWNLOAD_TIMEOUT = 45  # 下载超时（秒）
DOWNLOAD_MAX_RETRIES = 2
DOWNLOAD_MAX_CONCURRENT = 15  # 最大并发数
DOWNLOAD_RATE_LIMIT_PER_DOMAIN = 5  # 每域名最大并发
DOWNLOAD_CONNECTION_POOL_SIZE = 20  # HTTP连接池大小
MIN_FILE_SIZE = 10 * 1024  # 10KB
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

# 下载增强功能
DOWNLOAD_SHOW_PROGRESS = True  # 显示进度条
DOWNLOAD_ENABLE_STATS = True  # 启用统计

# ========== PubMed配置 ==========
PUBMED_EMAIL = os.getenv("PUBMED_EMAIL", "your_email@example.com")  # NCBI要求提供邮箱
PUBMED_API_KEY = os.getenv("PUBMED_API_KEY", "")  # 可选，有API Key可提高限速
PUBMED_MAX_RESULTS = 50  # 单次检索最大返回数
PUBMED_REQUEST_DELAY = 0.34  # 无API Key限速：3次/秒，有Key：10次/秒

# ========== PubMed下载配置 ==========
PUBMED_DOWNLOAD_FORMATS = ["pdf", "xml", "txt"]  # 下载格式优先级
PUBMED_DOWNLOAD_TIMEOUT = 60  # PubMed下载超时（秒）

# ========== Unpaywall/CORE配置 ==========
UNPAYWALL_EMAIL = os.getenv("UNPAYWALL_EMAIL", "")
CORE_API_KEY = os.getenv("CORE_API_KEY", "")

# ==========================================
# 提取子图配置（子图3）
# ==========================================

# ===== VLM配置 =====
VLM_CONCURRENCY = 20              # VLM并发线程数
VLM_MODEL = "qwen3.7-plus"        # VLM模型
VLM_MAX_TOKENS = 8192             # VLM最大输出tokens
VLM_TEMPERATURE = 0.1             # VLM温度
VLM_MAX_RETRIES = 3               # VLM最大重试次数

# ===== OCR配置 =====
OCR_CONCURRENCY = 20              # OCR并发线程数
OCR_MODEL = "qwen3.5-ocr"         # OCR模型
OCR_MAX_RETRIES = 3               # OCR最大重试次数
ENABLE_OCR_CACHE = True           # 是否持久化OCR结果
OCR_CACHE_DIR = "./data/ocr_cache"  # OCR缓存目录

# ===== 验证配置 =====
ENTITY_THRESHOLD = 90             # Entity验证阈值
PROPERTY_THRESHOLD = 95           # Property验证阈值

# ===== 提取配置 =====
MAX_PAGES_PER_PDF = None          # 每个PDF处理页数（None=全部）
ENABLE_EXTRACTION_REPORT = True   # 是否生成报告
REPORT_DIR = "./data/reports"     # 报告目录
