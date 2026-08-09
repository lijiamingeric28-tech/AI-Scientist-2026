"""pytest 共享 fixtures — 全 mock 离线测试底座

原则：
1. 所有网络/LLM 外部依赖在 fixture 层 mock，测试本身不联网
2. 每个 fixture 只做一件事，测试按需组合
3. 断言零网络：no_network fixture 记录 requests.get 调用，测试断言为空
"""

import importlib

import pytest


def _node_module(pkg: str, mod_name: str):
    """取真实节点模块。

    不能用 `import a.b.c as x`：nodes/__init__.py 会把节点函数 re-export，
    那样 x 绑定的是函数而非模块。importlib 按完整路径取模块对象。
    """
    return importlib.import_module(f"astroquery_ai.{pkg}.nodes.{mod_name}")


@pytest.fixture
def mock_sg1_llm(monkeypatch):
    """Mock 子图1 的 LLM 工具函数：输入 M31 查询 → 固定提取结果（离线）

    注意：initial_parse 节点用 `from ..utils import ...` 导入，
    import 时已绑定到节点模块命名空间——必须 patch 节点模块属性。
    """
    init_mod = _node_module("subgraph1", "initial_parse")
    monkeypatch.setattr(init_mod, "classify_query_type", lambda user_input: "astronomical")
    monkeypatch.setattr(
        init_mod,
        "extract_entity_and_properties",
        lambda user_input, chat_history: {
            "target_entity": "M31",
            "requested_properties": ["distance"],
        },
    )


@pytest.fixture
def mock_stdin(monkeypatch):
    """Patch 子图1 节点模块的 interrupt — 固定返回 'y'（确认检索）。

    Phase 4c: 节点 input() → interrupt()，mock 目标从 builtins.input
    改为各节点模块的 interrupt 属性（import 时绑定）。
    """
    for mod_name in ("ask_entity", "ask_properties", "greeting_handler", "final_confirm"):
        mod = _node_module("subgraph1", mod_name)
        monkeypatch.setattr(mod, "interrupt", lambda *a, **k: "y")


@pytest.fixture
def no_network(monkeypatch):
    """记录 requests.get 调用；测试断言返回列表为空 = 零网络请求"""
    import requests

    calls = []
    real_get = requests.get

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real_get(*args, **kwargs)

    monkeypatch.setattr(requests, "get", spy)
    return calls


def _ads_search_module():
    """取 ads_search 真实模块。

    不能用 `import a.b.c as x`：nodes/__init__.py 把 ads_search 重导出为函数，
    那样拿到的 x 是函数而非模块。importlib 直接按路径取模块。
    """
    import importlib
    return importlib.import_module("astroquery_ai.subgraph2.nodes.ads_search")


@pytest.fixture
def mock_ads_empty(monkeypatch):
    """Mock ads.SearchQuery：构造时即可用，迭代返回空（零论文）"""
    ads_search_mod = _ads_search_module()

    class _EmptySearchQuery:
        def __init__(self, *args, **kwargs):
            pass

        def __iter__(self):
            return iter([])

    monkeypatch.setattr(ads_search_mod.ads, "SearchQuery", _EmptySearchQuery)


@pytest.fixture
def mock_ads_rate_limit(monkeypatch):
    """Mock ads.SearchQuery：构造时抛 429 → ads_search 走 skipped 分支"""
    ads_search_mod = _ads_search_module()

    class _RateLimitSearchQuery:
        def __init__(self, *args, **kwargs):
            raise Exception("429 rate limit exceeded")

        def __iter__(self):
            return iter([])

    monkeypatch.setattr(ads_search_mod.ads, "SearchQuery", _RateLimitSearchQuery)


def make_minimal_pipeline_query():
    """构造最小主图输入（与 run.py 初始 state 一致）"""
    return {
        "user_query": "M31 的距离",
        "query_id": "test-query-id",
        "extra_pdfs": [],
        "error_log": [],
    }
