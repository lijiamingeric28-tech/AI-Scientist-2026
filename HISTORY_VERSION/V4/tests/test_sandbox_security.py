"""沙箱安全回归测试 (C1 fix) — 逃逸 PoC 全部必须被拦截。

覆盖: AST 白名单校验 (别名赋值/dunder 属性链) + sandbox 运行时防线
(_safe_import 白名单包装器; P0 起 type 放行 — §8 同步, dunder 属性块兜底)。

背景: 旧实现 safe_builtins 裸暴露 __import__/type, AST 黑名单只查 Call 的
func 名 — `_imp = __import__` (Name Load) 可绕过 → 任意代码执行。
P0 (b): operator/logging 移出模块白名单 (operator.attrgetter 字符串 dunder
路径完整任意代码执行), builtins 扩充 (reversed/type/... + 异常类)。
"""

import pytest

import quality_pipeline  # noqa: F401  # 先初始化顶层, 避免 agent 直接 import 的既有循环


@pytest.fixture(scope="module")
def sandbox_mods():
    from subgraphs.data_normalization.agents.normalization_agent import (
        _make_sandbox, _validate_code_ast,
    )
    return _make_sandbox(), _validate_code_ast  # 调用 _make_sandbox() 得到实际沙箱 dict


# ── 逃逸攻击 PoC (必须全部拦截) ──

_ESCAPE_POCS = [
    ("alias_import",
     '_imp = __import__\n_imp("os").system("echo pwned")'),
    ("direct_import",
     '__import__("os").system("echo pwned")'),
    ("import_os",
     'import os\nos.system("echo pwned")'),
    ("dunder_mro",
     'x = 1\nx.__class__.__mro__'),
    ("type_subclasses",
     't = 1\nfor c in t.__class__.__mro__: pass'),
    ("getattribute",
     'obj = {}\nobj.__getattribute__("__class__")'),
    ("bases_chain",
     'f = len\nf.__class__.__bases__'),
    ("eval_call",
     'eval("1+1")'),
    ("exec_call",
     'exec("x = 1")'),
    ("getattr_call",
     'getattr(obj, "__class__")'),
    # P0 (b): operator 移出白名单 (V1 实测字符串 dunder 路径任意代码执行)
    ("operator_attrgetter_escape",
     'import operator\n'
     'b = operator.attrgetter("__class__.__bases__")(())[0]\n'
     's = operator.attrgetter("__subclasses__")(b)()'),
    # P1 (a): NamedExpr/Match 节点放行后的逃逸路径 — 白名单放宽必须同时验证
    # 对应 PoC 仍拦截 (walrus/match 分支内的 dunder 属性链由 dunder 块拦截)
    ("walrus_escape",
     'if (t := type.__subclasses__):\n    pass'),
    ("match_escape",
     'match x:\n    case _:\n        type.__subclasses__'),
    # P1 (a): Name 黑名单 Load 上下文 — `x = eval` 中 eval 是 Load (别名绑定逃逸),
    # AST 直接拦截; 运行时防线 (eval 不在 safe_builtins → NameError) 另测
    ("store_eval_then_call",
     'x = eval\nx("1+1")'),
]


@pytest.mark.parametrize("name,code", _ESCAPE_POCS)
def test_escape_pocs_blocked(sandbox_mods, name, code):
    """AST 校验必须拦截全部逃逸 PoC。"""
    _, validate = sandbox_mods
    assert not validate(code), f"[{name}] 逃逸代码未被 AST 校验拦截"


def test_legit_code_allowed(sandbox_mods):
    """合法生成工具代码必须放行 (不误伤)。"""
    _, validate = sandbox_mods
    legit = (
        'def tool(records):\n'
        '    import math\n'
        '    return [{"record_id": r["record_id"], '
        '"value": math.sqrt(float(r["field_value"]))} for r in records]'
    )
    assert validate(legit), "合法工具代码被误拦截"


def test_legit_name_attr_allowed(sandbox_mods):
    """__name__ 白名单例外仍可用 (模板代码只作可读属性)。"""
    _, validate = sandbox_mods
    code = 'def tool(records):\n    return records\nx = tool.__name__'
    assert validate(code), "__name__ 应被白名单例外放行"


# ── sandbox 运行时防线 (AST 校验缺失时的第二道闸) ──

def test_runtime_import_os_blocked(sandbox_mods):
    sb, _ = sandbox_mods
    with pytest.raises(ImportError):
        exec('import os', sb)


def test_runtime_direct_import_blocked(sandbox_mods):
    sb, _ = sandbox_mods
    with pytest.raises(ImportError):
        exec('__import__("os")', sb)


def test_runtime_whitelisted_import_works(sandbox_mods):
    sb, _ = sandbox_mods
    exec('import math\nx = math.sqrt(4.0)', sb)
    assert sb.get("x") == 2.0


def test_type_subclasses_after_allow(sandbox_mods):
    """§8 同步 (P0 type 放行后): type 本身可用, __subclasses__ 逃逸链仍被拦截。

    安全前提: _validate_code_ast 的 dunder 属性块挡 type.__subclasses__/__mro__。
    """
    sb, validate = sandbox_mods
    exec('t = type(1)', sb)
    assert sb.get("t") is int
    assert not validate('x = type.__subclasses__')
    assert not validate('t = type(1)\nfor c in t.__mro__: pass')
    assert not validate('c = type(1).__class__.__bases__')
