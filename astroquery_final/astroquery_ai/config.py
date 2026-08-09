"""统一配置模块 — 全系统唯一配置入口（Phase 1 收敛）

历史：项目曾有 4 套互不相容的配置源（subgraph1/2 各一份 config.yaml、
subgraph3 settings.py、quality_pipeline llm_config.yaml），env/yaml 优先级
互相矛盾，且 quality_pipeline 从不加载 .env。
现在：一切配置收敛到本模块，env 优先 > 默认值兜底；.env 只在加载一次。

领域常量（关键词列表、UI 文案、星表路径等）不属于"配置"，保留在各子图
config 模块内联；本模块只负责敏感字段 + 运行参数。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（.env 所在处）
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """全系统唯一配置（env 优先，.env 自动加载一次）"""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",  # .env 中未知变量（如 LANGCHAIN_*）不报错
    )

    # ── 子图1 + P1：DashScope 兼容 API ──
    dashscope_api_key: str = ""
    dashscope_base_url: str = ""
    dashscope_model: str = "qwen3.7-flash"
    # 子图3 VLM 提取 / BBox 标注专用模型（原 settings.py dataclass 默认值，
    # 历史上有意区分：VLM 用 qwen3.7-plus，BBox 用 qwen3.7-flash）
    dashscope_vlm_model: str = "qwen3.7-plus"
    dashscope_bbox_model: str = "qwen3.7-flash"
    # P1 性质标准化专用模型（历史上与子图1 型号不同，硬编码在
    # property_standardization.py，Phase 1 收敛到此）
    p1_model: str = "qwen3.8-max"
    # 子图1 LLM 调用参数（原 config.yaml llm 段的温度/最大 token）
    llm_temperature: float = 0.1
    llm_max_tokens: int = 500

    # ── 子图2：论文检索 ──
    ads_api_token: str = ""
    unpaywall_email: str = ""

    # ── quality_pipeline：OpenAI 兼容 API（原 llm_config.yaml）──
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "deepseek-v4-flash"
    llm_timeout: int = 120
    llm_max_retries: int = 3

    # ── scripts/add_units.py：批量补单位 ──
    deepseek_api_key: str = ""

    # ── 通用 ──
    default_research_domain: str = "astrophysics"


@lru_cache
def get_settings() -> Settings:
    """获取全局 Settings 单例（lru_cache 保证只解析一次 .env）"""
    return Settings()
