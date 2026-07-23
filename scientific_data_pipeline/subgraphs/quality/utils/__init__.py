from .logger import get_logger
from .retry import retry_on_failure

__all__ = ["get_logger", "retry_on_failure"]


def __getattr__(name):
    if name in ("get_llm", "get_structured_llm", "set_agent_context",
                 "get_llm_stats", "reset_llm_stats", "print_llm_stats",
                 "track_raw_llm_call", "StructuredLLM"):
        import subgraphs.quality.utils.llm as _llm
        return getattr(_llm, name)
    raise AttributeError(f"module 'subgraphs.quality.utils' has no attribute '{name}'")
