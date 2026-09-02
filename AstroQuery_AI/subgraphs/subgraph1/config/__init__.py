"""配置模块（Phase 1 收敛）

历史：从 config.yaml 加载，敏感字段 env 优先 yaml 兜底。
现在：敏感字段（llm 三件套）来自统一 Settings（astroquery_ai/config.py），
业务常量（关键词、性质列表、UI 文案）内联为 Python 常量。
接口不变（config.llm / config.ui / config.clarification 等），节点代码零改动。
"""

from astroquery_ai.config import get_settings

_settings = get_settings()

# ── 业务常量（原 config.yaml，非敏感，内联）──
_CLARIFICATION = {
    "max_turns": 3,  # 最大追问轮次
    "default_entity_type": "unknown",  # 默认天体类型
}

_EXIT_KEYWORDS = [
    "算了", "不查了", "退出", "取消", "放弃",
    "quit", "exit", "bye", "goodbye",
]

_GREETING_KEYWORDS = [
    "你好", "您好", "hi", "hello", "hey", "在吗",
]

_COMMON_PROPERTIES = [
    "distance", "redshift", "metallicity", "luminosity", "mass",
    "temperature", "magnitude", "parallax", "velocity", "age",
]

_UI = {
    "separator": "=" * 60,
    "user_input_prompt": "请输入：",
    "confirm_prompt": "请输入 (y/m/n)：",
}

_LOGGING = {
    "level": "DEBUG",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
}


class Config:
    """配置类：敏感字段来自统一 Settings，业务常量内联"""

    @property
    def llm(self):
        s = _settings
        return {
            "api_key": s.dashscope_api_key,
            "base_url": s.dashscope_base_url,
            "model": s.dashscope_model,
            "temperature": s.llm_temperature,
            "max_tokens": s.llm_max_tokens,
        }

    @property
    def clarification(self):
        return _CLARIFICATION

    @property
    def exit_keywords(self):
        return _EXIT_KEYWORDS

    @property
    def greeting_keywords(self):
        return _GREETING_KEYWORDS

    @property
    def common_properties(self):
        return _COMMON_PROPERTIES

    @property
    def ui(self):
        return _UI

    @property
    def logging(self):
        return _LOGGING


# 全局配置实例（接口兼容：节点代码引用 config.xxx）
config = Config()
