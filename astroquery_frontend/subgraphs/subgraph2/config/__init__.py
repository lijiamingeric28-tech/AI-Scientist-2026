"""配置模块（Phase 1 收敛）

历史：从 config.yaml 加载，ADS/Unpaywall 敏感字段 env 覆盖，相对路径按包根解析。
现在：敏感字段（ADS token / Unpaywall email）来自统一 Settings
（astroquery_ai/config.py），其余为业务常量内联；路径解析逻辑保留。
接口不变（config.api / config.retrieval / get_catalog_* 等），节点代码零改动。
"""

from pathlib import Path

from astroquery_ai.config import get_settings

_settings = get_settings()

# 包内锚点：
#   SUBGRAPH_ROOT = astroquery_ai/subgraph2
#   PACKAGE_ROOT  = astroquery_ai
SUBGRAPH_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = SUBGRAPH_ROOT.parent

# ── 业务常量（原 config.yaml，非敏感，内联）──
_RETRIEVAL = {
    "simbad": {
        "max_retries": 3,
        "retry_backoff": 3,
        "timeout": 30,
    },
    "database": {
        "total_catalogs": 22,
        "sequential_query": True,  # 顺序查询（避免触发VizieR限流）
    },
    "papers": {
        "ads_max_papers": 50,
        "ads_sort": "score desc",
        "pdf_download": {
            "max_workers": 5,
            "timeout": 60,
            "max_file_size_mb": 50,
            "arxiv_max_workers": 3,
            "arxiv_delay": 1.0,
        },
    },
    "performance_targets": {
        "simbad": 5,
        "database_total": 30,
        "ads_search": 10,
        "unpaywall_batch": 15,
        "pdf_download_total": 60,
        "total": 90,
    },
}

_LOGGING = {
    "level": "DEBUG",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "file": {
        "enabled": True,
        "path": "data/logs/subgraph2.log",
        "max_bytes": 10485760,
        "backup_count": 5,
    },
}

_OUTPUT = {
    "data_dir": "data",
    "papers_dir": "data/papers",
    "output_format": "json",
    "save_intermediate_states": False,
}

_CONFIG_FILES = {
    "catalog_config": "catalog/catalog_config.json",
    "catalog_metadata": "catalog/catalog_metadata.json",
    "catalog_units": "catalog/catalog_units.json",
}


class Config:
    """配置类：敏感字段来自统一 Settings，业务常量内联"""

    def __init__(self):
        # 输出目录/日志文件的相对路径按包根解析为绝对路径（保留历史逻辑）
        self._resolve_paths()

    def _resolve_paths(self) -> None:
        """把配置中的相对路径统一解析为绝对路径（相对包根，而非 CWD）"""
        def to_abs(value: str) -> str:
            p = Path(value)
            return str(p if p.is_absolute() else (PACKAGE_ROOT / p).resolve())

        # 2026-09-02：绿色包外置数据目录机制已移除——统一相对包根解析
        for key in ("data_dir", "papers_dir"):
            if key in _OUTPUT:
                _OUTPUT[key] = to_abs(_OUTPUT[key])

    @property
    def api(self):
        s = _settings
        return {
            "ads": {
                "token": s.ads_api_token,
                "timeout": 30,
                "max_retries": 3,
                "retry_backoff": 3,
            },
            "unpaywall": {
                "email": s.unpaywall_email,
                "timeout": 30,
                "max_workers": 10,
            },
            "vizier": {
                "server": "vizier.cfa.harvard.edu",
                "timeout": 30,
                "row_limit": 10,
                "rate_limit_delay": 0.15,
            },
        }

    @property
    def retrieval(self):
        return _RETRIEVAL

    @property
    def logging(self):
        return _LOGGING

    @property
    def output(self):
        return _OUTPUT

    @property
    def config_files(self):
        return _CONFIG_FILES

    def _catalog_path(self, key: str) -> Path:
        """
        解析星表配置文件路径

        配置值可以是：
        - 绝对路径：直接使用
        - 相对路径：相对 subgraph2/ 解析（catalog/*.json 随包分发）
        """
        p = Path(_CONFIG_FILES[key])
        return p if p.is_absolute() else (SUBGRAPH_ROOT / p).resolve()

    def get_catalog_config_path(self) -> Path:
        """获取星表配置文件路径"""
        return self._catalog_path("catalog_config")

    def get_catalog_metadata_path(self) -> Path:
        """获取星表元数据文件路径"""
        return self._catalog_path("catalog_metadata")

    def get_catalog_units_path(self) -> Path:
        """获取星表单位配置文件路径"""
        return self._catalog_path("catalog_units")


# 全局配置实例（接口兼容：节点代码引用 config.xxx）
config = Config()
