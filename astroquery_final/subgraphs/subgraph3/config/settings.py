"""提取子图配置。

Phase 1 收敛：API key 与模型名来自统一 Settings（astroquery_ai/config.py），
不再自行加载 .env。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from astroquery_ai.config import get_settings

# 包内锚点：PACKAGE_ROOT = astroquery_ai
PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent

_settings = get_settings()


@dataclass
class VLMConfig:
    """VLM 模型配置。"""
    model: str = field(default_factory=lambda: _settings.dashscope_vlm_model)
    temperature: float = 0.0
    max_tokens: int = 65536
    timeout: int = 600  # Timeout in seconds (increased to 10 minutes)
    api_key: str = ""

    def __post_init__(self):
        # 只读取，不校验。
        # 校验推迟到真正发起 VLM 请求时（见 ensure_api_key），
        # 这样"只查数据库、不提取论文"的流程无需配置此密钥。
        self.api_key = _settings.dashscope_api_key

    def ensure_api_key(self) -> str:
        """在真正调用 VLM 之前校验密钥，缺失则抛错。"""
        # 支持运行期才写入环境变量的场景
        if not self.api_key:
            self.api_key = _settings.dashscope_api_key
        if not self.api_key:
            raise ValueError(
                "DASHSCOPE_API_KEY environment variable not set. "
                "Please set it in your .env file or with: export DASHSCOPE_API_KEY=your_api_key"
            )
        return self.api_key


@dataclass
class PDFConfig:
    """PDF 转换配置。"""
    dpi: int = 100
    format: str = "PNG"


@dataclass
class ConcurrencyConfig:
    """并发配置。"""
    max_workers: int = 15


@dataclass
class QualityConfig:
    """质量控制配置。"""
    min_confidence: float = 0.7
    max_retries: int = 3  # Retry up to 3 times for JSON parsing failures
    max_timeout_retries: int = 5  # Retry up to 5 times for timeout errors


@dataclass
class BBoxVLMConfig:
    """BBox 标注 VLM 配置。"""
    model: str = field(default_factory=lambda: _settings.dashscope_bbox_model)
    temperature: float = 0.0  # Deterministic output
    max_tokens: int = 500  # Two-stage analysis + coordinates


@dataclass
class BBoxConcurrencyConfig:
    """BBox 标注并发配置。"""
    max_workers: int = 100  # Data-point level concurrency
    max_retries: int = 3  # Max retries per data point
    retry_delay_base: int = 2  # Retry delay base (seconds)


@dataclass
class LogConfig:
    """日志配置。"""
    level: str = "DEBUG"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    console_output: bool = True
    file_output: bool = True
    # 绝对路径，基于包根解析，不依赖当前工作目录
    log_dir: str = str(PACKAGE_ROOT / "data" / "logs")
    log_file: str = "extraction_subgraph.log"


@dataclass
class Settings:
    """全局配置。"""
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


# 全局配置实例
settings = Settings()
