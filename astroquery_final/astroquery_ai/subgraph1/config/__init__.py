"""配置模块

YAML 加载后，下面三个 key 会优先从环境变量取值（yaml 值作为兜底）：
  - DASHSCOPE_API_KEY → llm.api_key
  - DASHSCOPE_BASE_URL  → llm.base_url
  - DASHSCOPE_MODEL     → llm.model
"""

import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

# 包内锚点：SUBGRAPH_ROOT = astroquery_ai/subgraph1, PACKAGE_ROOT = astroquery_ai
SUBGRAPH_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = SUBGRAPH_ROOT.parent

# 显式加载 .env（不依赖 CWD）：优先包内，其次项目根，其次默认搜索
for _env in (PACKAGE_ROOT / ".env", PACKAGE_ROOT.parent / ".env"):
    if _env.exists():
        load_dotenv(_env)
load_dotenv()


class Config:
    """配置类，从 YAML 加载后，敏感字段优先读取环境变量"""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = SUBGRAPH_ROOT / "config" / "config.yaml"

        with open(config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

    @property
    def llm(self):
        raw = dict(self._config.get('llm', {}))
        raw['api_key'] = os.getenv('DASHSCOPE_API_KEY', raw.get('api_key', ''))
        raw['base_url'] = os.getenv('DASHSCOPE_BASE_URL', raw.get('base_url', ''))
        raw['model'] = os.getenv('DASHSCOPE_MODEL', raw.get('model', ''))
        return raw

    @property
    def clarification(self):
        return self._config['clarification']
    @property
    def exit_keywords(self):
        return self._config['exit_keywords']
    @property
    def greeting_keywords(self):
        return self._config['greeting_keywords']
    @property
    def common_properties(self):
        return self._config['common_properties']
    @property
    def ui(self):
        return self._config['ui']
    @property
    def logging(self):
        return self._config['logging']

# 全局配置实例
config = Config()
