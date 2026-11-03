"""AstroQuery AI. Importing the public package never starts execution."""
__version__ = "3.0.0-dev"


def run_pipeline(*args, **kwargs):
    from .runtime.errors import DomainError
    raise DomainError("EXPLICIT_CONFIRMATION_REQUIRED", "请创建草稿、核验身份并明确确认后开始检索；旧裸查询执行入口已退出", 410)


def create_main_graph(dispatch):
    from .runtime.main_graph import create_main_graph as build
    return build(dispatch)

__all__ = ["create_main_graph", "run_pipeline", "__version__"]
