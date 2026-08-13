"""端到端录制回放测试（测试策略第 2 层：VCR 录制一次，之后免费回放）。

第一次运行（真实 LLM，花一次钱）：
    python -m pytest tests/test_e2e_recorded.py -m network -v

之后（回放，零费用）：
    同命令（cassette 命中缓存）

说明：
- cassette 存 tests/cassettes/（已 gitignore——这是你的"录制资产"）
- 录制内容：子图1 澄清 + P1 + 检索列名映射 + VLM + 质量管线全部 LLM HTTP 请求
- H-13：录制一律 filter_headers 脱敏 authorization 头 / filter_query_parameters
  脱敏查询参数，cassette 永不落盘明文密钥；cassette 文件本身已清空历史明文
  Bearer 密钥（test_cassette_contains_no_secrets 锚点）
- H-16：E2E 断言升级为内容/数值/顺序契约（assert_m13_contract），
  VCR 错位数据（项目自述头号已知问题）下必须红；断言助手有离线注入回归
- 前端联调：后端加 LLM_CASSETTE 环境变量启动即进入回放模式（见 README 指引）
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import pytest
import vcr

from astroquery_ai.web_runner import run_task_streaming
from web.event_bus import EventBus
from web.task_store import TaskStore

CASSETTE_DIR = Path(__file__).parent / "cassettes"
CASSETTE_DIR.mkdir(exist_ok=True)

# H-13：录制脱敏——请求头 authorization 与查询参数中的密钥一律不落盘
_FILTER_HEADERS = [("authorization", None)]
_FILTER_QUERY = ["api_key", "apikey", "access_token", "token", "signature", "X-Amz-Signature"]

my_vcr = vcr.VCR(
    record_mode="once",            # 第一次录制，之后回放
    cassette_library_dir=str(CASSETTE_DIR),
    decode_compressed_response=False,
    filter_headers=_FILTER_HEADERS,
    filter_query_parameters=_FILTER_QUERY,
)


# ══════════════════════════════════════════════════════
# H-16：E2E 契约断言助手（内容/数值/顺序，防 VCR 错位数据）
# ══════════════════════════════════════════════════════

REQUIRED_PROPERTY_TERMS = ("距离", "年龄", "金属丰度")

# 图驱动 stage 事件面（与 astroquery_ai/main_graph.py `_NODES` 阶段映射一致）：
#   clarification/property_std → understand；quality_finalize → done。
#   clean/deliver 卡无 stage 事件（前端由 agent 事件自动弹卡，勿要求之）；
#   understand 澄清重入可多次 stage_started（H-09④ 同实例去重仅防重复 start）。
GRAPH_STAGE_STARTED = {"understand", "retrieval", "extraction", "quality_check"}
GRAPH_STAGE_COMPLETED = GRAPH_STAGE_STARTED | {"done"}


def assert_m13_contract(final: dict, events: list) -> None:
    """H-16 锚点：最终结果 + 事件流的五维契约断言（错位数据下必须红）。

    ① target_entity==M13 且 requested_properties 含 距离/年龄/金属丰度；
    ② records 非空且每条 field_name/field_value/field_unit 非空；
    ③ 图驱动 7 卡 stage_started 全集 + stage_completed 配对；
    ④ 事件 seq 严格单调递增（乱序/重放/断线续播防线）。
    """
    # ① 目标天体与查询性质（错位响应最常见表现：另一论文/另一天体）
    assert final.get("target_entity") == "M13", \
        f"target_entity 错位: {final.get('target_entity')!r}"
    props = final.get("requested_properties") or []
    props_text = " ".join(str(p) for p in props)
    for term in REQUIRED_PROPERTY_TERMS:
        assert term in props_text, f"requested_properties 缺少 {term}: {props!r}"

    # ② records 非空 + 每条记录字段非空（'records' 键存在 ≠ 数据正确）
    records = (final.get("final_output") or {}).get("records") or []
    assert records, "records 为空（VCR 错位或上游断链）"
    for i, rec in enumerate(records):
        for key in ("field_name", "field_value", "field_unit"):
            val = rec.get(key)
            assert val is not None and str(val).strip() != "", \
                f"record[{i}].{key} 为空: {rec!r}"

    # ③ 阶段事件配对（干净样本：started 全集 = 图驱动集；每 started 必有 completed；
    #    任务完成卡 done 必须 stage_completed）
    started = {e.get("stage_id") for e in events if e.get("type") == "stage_started"}
    completed = {e.get("stage_id") for e in events if e.get("type") == "stage_completed"}
    assert started == GRAPH_STAGE_STARTED, f"stage_started 集合错位: {sorted(started)}"
    assert GRAPH_STAGE_COMPLETED <= completed, \
        f"stage_completed 缺失: {sorted(GRAPH_STAGE_COMPLETED - completed)}"

    # ④ 事件 seq 严格单调递增（seq 由 TaskStore 自增分配，乱序即异常注入）
    seqs = [e.get("seq") for e in events]
    assert all(isinstance(s, int) and s > 0 for s in seqs), f"seq 缺失或非法: {seqs[:5]}"
    assert all(a < b for a, b in zip(seqs, seqs[1:])), "事件 seq 非严格单调递增（乱序注入）"


@pytest.mark.network
@my_vcr.use_cassette("m13_query.yaml")
def test_e2e_m13_query(tmp_path):
    """真实全流程：M13 的距离、年龄和金属丰度（录制/回放）。"""
    store = TaskStore(tmp_path / "e2e.db")
    task = store.create_task("M13 的距离、年龄和金属丰度")

    tbus = EventBus(store)

    answers = iter(["距离、年龄和金属丰度", "y"])  # ask_properties → final_confirm

    def get_answer(_tid, payload):
        return next(answers)

    result = run_task_streaming(
        task_id=task["task_id"],
        user_query="M13 的距离、年龄和金属丰度",
        extra_pdfs=[],
        bus=tbus,
        get_answer=get_answer,
        should_cancel=lambda: False,
        checkpointer_path=str(tmp_path / "cp.sqlite"),
    )

    events = store.get_events(task["task_id"])
    # H-16：内容/数值/顺序契约断言（VCR 错位数据下必须红）
    assert_m13_contract(result, events)

    # 澄清至少一次（ask_properties 或 final_confirm）且终态事件在场
    types = [e["type"] for e in events]
    clar = [e for e in events if e["type"] == "clarification"]
    assert len(clar) >= 1
    assert "task_completed" in types

    final = (result.get("final_output") or {})
    records = final.get("records", [])
    print(f"\n[E2E] 事件 {len(events)} 条 · records {len(records)} 条 · sources {len(final.get('sources', []))} 个")
    print(f"[E2E] 目标天体: {result.get('target_entity')} · 性质: {result.get('requested_properties')}")


# ══════════════════════════════════════════════════════
# H-13：cassette 密钥泄露回归锚点（grep 断言无 authorization 键）
# ══════════════════════════════════════════════════════

_AUTH_KEY_RE = re.compile(r"^\s*authorization\s*:\s*$", re.IGNORECASE)
_SECRET_RE = re.compile(r"Bearer\s+sk-|sk-ws-")


def test_cassette_contains_no_secrets():
    """H-13：cassette 不得含 authorization 头键或明文 Bearer 密钥。

    录制端已配 filter_headers/filter_query_parameters；本测试守护已落盘
    的 m13_query.yaml（58MB，141 条交互）不含任何密钥痕迹。
    """
    path = CASSETTE_DIR / "m13_query.yaml"
    assert path.exists(), "cassette 缺失（录制资产被误删？）"
    bad: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if _AUTH_KEY_RE.match(line.rstrip("\r\n")):
                bad.append(f"line {lineno}: 残留 authorization 头键（应被脱敏）")
            elif _SECRET_RE.search(line):
                bad.append(f"line {lineno}: 残留明文 Bearer 密钥")
    assert not bad, "\n".join(bad)


# ══════════════════════════════════════════════════════
# H-16：断言助手离线回归（注入错位数据 → 断言必须失败）
# ══════════════════════════════════════════════════════

def _sample_final(**overrides) -> dict:
    """干净样本：真实 M13 运行形态（target_entity/props/records 与实测一致）。"""
    final = {
        "target_entity": "M13",
        "requested_properties": ["距离", "年龄", "金属丰度"],
        "final_output": {
            "records": [
                {"field_name": "distance_sun", "field_value": "7107", "field_unit": "pc"},
                {"field_name": "cluster_age", "field_value": "12.9 Gyr", "field_unit": "Gyr"},
                {"field_name": "cluster_metallicity", "field_value": "-1.39", "field_unit": "dex"},
            ]
        },
    }
    final.update(overrides)
    return final


def _sample_events() -> list:
    """干净样本：真实运行的事件形态（seq 自增；understand 澄清重入双 start）。"""
    seq = itertools.count(1)
    events = [
        {"seq": next(seq), "type": "stage_started", "stage_id": "understand", "name": "任务理解"},
        {"seq": next(seq), "type": "clarification", "cl_type": "ask_properties", "stage_id": "understand"},
        {"seq": next(seq), "type": "stage_started", "stage_id": "understand", "name": "任务理解"},
        {"seq": next(seq), "type": "stage_started", "stage_id": "retrieval", "name": "数据检索"},
        {"seq": next(seq), "type": "stage_started", "stage_id": "extraction", "name": "数据提取"},
        {"seq": next(seq), "type": "stage_started", "stage_id": "quality_check", "name": "质量检查"},
        {"seq": next(seq), "type": "stage_completed", "stage_id": "understand", "status": "completed"},
        {"seq": next(seq), "type": "stage_completed", "stage_id": "retrieval", "status": "completed"},
        {"seq": next(seq), "type": "stage_completed", "stage_id": "extraction", "status": "completed"},
        {"seq": next(seq), "type": "stage_completed", "stage_id": "quality_check", "status": "completed"},
        {"seq": next(seq), "type": "stage_completed", "stage_id": "done", "status": "completed"},
        {"seq": next(seq), "type": "task_completed", "summary": "任务完成"},
    ]
    return events


def _swap_seq(events: list, i: int, j: int) -> None:
    events[i]["seq"], events[j]["seq"] = events[j]["seq"], events[i]["seq"]


def _mutate_missing_stage_started(final, events):
    events.remove(next(e for e in events if e["type"] == "stage_started" and e["stage_id"] == "retrieval"))


def _mutate_missing_stage_completed_done(final, events):
    events.remove(next(e for e in events if e["type"] == "stage_completed" and e["stage_id"] == "done"))


def _mutate_seq_out_of_order(final, events):
    _swap_seq(events, 2, 3)


def test_m13_contract_accepts_valid_data():
    """干净样本通过：E2E 契约对真实形态数据全绿。"""
    assert_m13_contract(_sample_final(), _sample_events())


@pytest.mark.parametrize(
    "label, mutate",
    [
        ("target_entity 错位", lambda f, e: f.update(target_entity="M31")),
        ("requested_properties 缺性质", lambda f, e: f.update(requested_properties=["距离"])),
        ("records 为空", lambda f, e: f["final_output"].update(records=[])),
        ("field_value 为空串", lambda f, e: f["final_output"]["records"][1].update(field_value="   ")),
        ("field_name 缺失", lambda f, e: f["final_output"]["records"][0].pop("field_name")),
        ("field_unit 缺失", lambda f, e: f["final_output"]["records"][0].pop("field_unit")),
        ("stage_started 缺卡", _mutate_missing_stage_started),
        ("stage_completed 缺 done", _mutate_missing_stage_completed_done),
        ("seq 乱序", _mutate_seq_out_of_order),
    ],
)
def test_m13_contract_rejects_mismatched_data(label, mutate):
    """注入错位数据 → 断言必须失败（H-16 回归锚点）。"""
    final, events = _sample_final(), _sample_events()
    mutate(final, events)
    with pytest.raises(AssertionError):
        assert_m13_contract(final, events)
