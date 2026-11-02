"""打包态（PyInstaller frozen）输出目录回归测试 — 全 mock 离线

2026-09-04 事故：exe 任务详情「任务数据包」JSON 全部缺失。
根因：data_export / data_insights 的默认输出目录按包根相对路径
（dirname(__file__) 上三级）计算；frozen（onedir）下包根 = sys._MEIPASS =
_internal/，导出文件全部落进 <包>/_internal/output/{run_id[:8]}/，
而 web API 扫描的是 exe 旁 output/{task_id[:8]}/（web.main.OUTPUT_DIR），
两侧路径分裂 → 前端「任务数据包」列表恒空。源码态包根恰与 web ROOT
相同，故源码运行正常。

本测试锁定：frozen 模式输出目录必须解析到 exe 旁（sys.executable 同目录）。
"""

import os
import sys

import pytest

# 先加载质量管线整链（quality_pipeline.__init__ → graph → export_graph → agent），
# 避免后续直接 import agent 时触发部分初始化回环（本测试仅做路径断言，不跑图）
import quality_pipeline.graph  # noqa: F401

import subgraphs.data_export.agents.export_generation_agent as export_agent
import subgraphs.data_insights.agents.synthesis_agent as insights_agent


def _fake_frozen(monkeypatch, tmp_path):
    """模拟 PyInstaller onedir 冻结态：frozen=True，exe 位于 tmp_path 下。"""
    exe = tmp_path / "AstroQueryAI.exe"
    exe.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)  # 存在才 patch；不存在则注入（frozen 语义 getattr 默认值）
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.delenv("EXPORT_OUTPUT_DIR", raising=False)
    return tmp_path


@pytest.mark.parametrize(
    "agent",
    [export_agent, insights_agent],
    ids=["data_export", "data_insights"],
)
def test_default_output_dir_frozen_uses_exe_side(monkeypatch, tmp_path, agent):
    """frozen 态：输出目录 = exe 旁 output/（与 web.main.OUTPUT_DIR 同口径）。"""
    exe_dir = _fake_frozen(monkeypatch, tmp_path)
    assert agent._default_output_dir() == os.path.join(str(exe_dir), "output")


@pytest.mark.parametrize(
    "agent",
    [export_agent, insights_agent],
    ids=["data_export", "data_insights"],
)
def test_default_output_dir_source_uses_package_root(agent):
    """源码态：输出目录 = 包根 output/（原行为不变）。"""
    agent_file = os.path.abspath(sys.modules[agent.__name__].__file__)
    pkg_root = os.path.normpath(os.path.join(os.path.dirname(agent_file), "..", "..", ".."))
    # 实现返回含 .. 的相对段（历史行为，使用点经 abspath 归一）——规范后对比
    assert os.path.normpath(agent._default_output_dir()) == os.path.join(pkg_root, "output")


def test_export_resolve_frozen_points_to_exe_output_run_dir(monkeypatch, tmp_path):
    """事故现场复现：frozen 下 _resolve_output_dir 必须落 exe 旁 output/{run_id[:8]}。"""
    exe_dir = _fake_frozen(monkeypatch, tmp_path)
    state = {"workflow_state": {"run_id": "ab3046a2-e027-48f1-9fc9-d0cba55dcd58"}}
    out = export_agent._resolve_output_dir(state)
    assert out == os.path.join(str(exe_dir), "output", "ab3046a2")


def test_insights_resolve_frozen_fallback_points_to_exe_output(monkeypatch, tmp_path):
    """insights 兜底路径（无 export output_dir 可复用时）同样落地 exe 旁。"""
    exe_dir = _fake_frozen(monkeypatch, tmp_path)
    state = {"output_state": {}, "workflow_state": {"run_id": "0eab300fde11"}}
    out = insights_agent._resolve_output_dir(state, state.get("workflow_state", {}))
    assert out == os.path.join(str(exe_dir), "output", "0eab300f")
