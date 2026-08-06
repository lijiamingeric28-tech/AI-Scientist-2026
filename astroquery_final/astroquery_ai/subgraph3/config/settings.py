"""Configuration settings for extraction subgraph."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# 包内锚点：PACKAGE_ROOT = astroquery_ai
PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent

# 显式加载 .env（不依赖 CWD）：优先包内，其次项目根
for _env in (PACKAGE_ROOT / ".env", PACKAGE_ROOT.parent / ".env"):
    if _env.exists():
        load_dotenv(_env)
load_dotenv()


@dataclass
class VLMConfig:
    """VLM model configuration."""
    model: str = "qwen3.7-plus"
    temperature: float = 0.0
    max_tokens: int = 65536
    timeout: int = 600  # Timeout in seconds (increased to 10 minutes)
    api_key: str = ""

    def __post_init__(self):
        # 只读取，不校验。
        # 校验推迟到真正发起 VLM 请求时（见 ensure_api_key），
        # 这样"只查数据库、不提取论文"的流程无需配置此密钥。
        self.api_key = os.getenv("DASHSCOPE_API_KEY", "")

    def ensure_api_key(self) -> str:
        """在真正调用 VLM 之前校验密钥，缺失则抛错。"""
        # 支持运行期才写入环境变量的场景
        if not self.api_key:
            self.api_key = os.getenv("DASHSCOPE_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "DASHSCOPE_API_KEY environment variable not set. "
                "Please set it in your .env file or with: export DASHSCOPE_API_KEY=your_api_key"
            )
        return self.api_key


@dataclass
class PDFConfig:
    """PDF conversion configuration."""
    dpi: int = 100
    format: str = "PNG"


@dataclass
class ConcurrencyConfig:
    """Concurrency configuration."""
    max_workers: int = 15


@dataclass
class QualityConfig:
    """Quality control configuration."""
    min_confidence: float = 0.7
    max_retries: int = 3  # Retry up to 3 times for JSON parsing failures
    max_timeout_retries: int = 5  # Retry up to 5 times for timeout errors


@dataclass
class BBoxVLMConfig:
    """BBox annotation VLM configuration."""
    model: str = "qwen3.7-flash"  # 🔒 Locked to qwen3.7-flash
    temperature: float = 0.0  # Deterministic output
    max_tokens: int = 500  # Two-stage analysis + coordinates


@dataclass
class BBoxConcurrencyConfig:
    """BBox annotation concurrency configuration."""
    max_workers: int = 100  # Data-point level concurrency
    max_retries: int = 3  # Max retries per data point
    retry_delay_base: int = 2  # Retry delay base (seconds)


@dataclass
class LogConfig:
    """Logging configuration."""
    level: str = "DEBUG"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    console_output: bool = True
    file_output: bool = True
    # 绝对路径，基于包根解析，不依赖当前工作目录
    log_dir: str = str(PACKAGE_ROOT / "data" / "logs")
    log_file: str = "extraction_subgraph.log"


@dataclass
class Settings:
    """Global settings."""
    vlm: VLMConfig
    pdf: PDFConfig
    concurrency: ConcurrencyConfig
    quality: QualityConfig
    bbox_vlm: BBoxVLMConfig
    bbox_concurrency: BBoxConcurrencyConfig
    log: LogConfig

    def __init__(self):
        self.vlm = VLMConfig()
        self.pdf = PDFConfig()
        self.concurrency = ConcurrencyConfig()
        self.quality = QualityConfig()
        self.bbox_vlm = BBoxVLMConfig()
        self.bbox_concurrency = BBoxConcurrencyConfig()
        self.log = LogConfig()


# Global settings instance
settings = Settings()
