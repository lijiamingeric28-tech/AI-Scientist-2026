"""utils/ — 通用工具"""
from utils.logger import get_logger
from utils.retry import retry_on_failure

def __getattr__(name):
    if name in ("get_llm", "get_structured_llm", "set_agent_context",
                 "get_llm_stats", "reset_llm_stats", "print_llm_stats"):
        import utils.llm as _llm
        return getattr(_llm, name)
    raise AttributeError(name)
