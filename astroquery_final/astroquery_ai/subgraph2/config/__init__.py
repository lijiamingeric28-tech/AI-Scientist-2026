"""配置模块"""

import yaml
import os
from pathlib import Path
from dotenv import load_dotenv

# 包内锚点：
#   SUBGRAPH_ROOT = astroquery_ai/subgraph2
#   PACKAGE_ROOT  = astroquery_ai
# 所有路径都基于这两个锚点解析，不依赖当前工作目录（CWD）。
SUBGRAPH_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = SUBGRAPH_ROOT.parent

# 显式加载 .env（不依赖 CWD）：优先包内，其次项目根
for _env in (PACKAGE_ROOT / ".env", PACKAGE_ROOT.parent / ".env"):
    if _env.exists():
        load_dotenv(_env)
# 兜底：再按默认规则搜一次（不覆盖已加载的变量）
load_dotenv()


class Config:
    """配置类，从YAML文件和环境变量加载配置"""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"

        with open(config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

        # 从环境变量覆盖API配置
        self._load_env_overrides()
        # 把 YAML 里的相对路径解析为绝对路径
        self._resolve_paths()

    def _resolve_paths(self):
        """把配置中的相对路径统一解析为绝对路径（相对包根，而非 CWD）"""
        def to_abs(value: str) -> str:
            p = Path(value)
            return str(p if p.is_absolute() else (PACKAGE_ROOT / p).resolve())

        # 输出目录
        out = self._config.get('output', {})
        for key in ('data_dir', 'papers_dir'):
            if key in out:
                out[key] = to_abs(out[key])

        # 日志文件
        log_file = self._config.get('logging', {}).get('file', {})
        if 'path' in log_file:
            log_file['path'] = to_abs(log_file['path'])

    def _load_env_overrides(self):
        """从环境变量加载敏感配置"""
        # ADS API Token
        ads_token = os.getenv('ADS_API_TOKEN')
        if ads_token:
            self._config['api']['ads']['token'] = ads_token

        # Unpaywall Email
        unpaywall_email = os.getenv('UNPAYWALL_EMAIL')
        if unpaywall_email:
            self._config['api']['unpaywall']['email'] = unpaywall_email

    @property
    def api(self):
        return self._config['api']

    @property
    def retrieval(self):
        return self._config['retrieval']

    @property
    def logging(self):
        return self._config['logging']

    @property
    def output(self):
        return self._config['output']

    @property
    def config_files(self):
        return self._config['config_files']

    def _catalog_path(self, key: str) -> Path:
        """
        解析星表配置文件路径

        配置值可以是：
        - 绝对路径：直接使用
        - 相对路径：相对 subgraph2/ 解析（catalog/*.json 随包分发）
        """
        p = Path(self.config_files[key])
        return p if p.is_absolute() else (SUBGRAPH_ROOT / p).resolve()

    def get_catalog_config_path(self) -> Path:
        """获取星表配置文件路径"""
        return self._catalog_path('catalog_config')

    def get_catalog_metadata_path(self) -> Path:
        """获取星表元数据文件路径"""
        return self._catalog_path('catalog_metadata')

    def get_catalog_units_path(self) -> Path:
        """获取星表单位配置文件路径"""
        return self._catalog_path('catalog_units')


# 全局配置实例
config = Config()
