# -*- coding: utf-8 -*-
"""演示队列自动确认器：轮询 running 任务的澄清事件，自动 resume 标准答案。

背景：P1 澄清子图对每个天文查询强制 final_confirm interrupt（等待 y/m/n），
executor 15 分钟超时自动取消（CLARIFICATION_TIMEOUT）。本脚本模拟人工确认，
不改系统代码，走公开 resume API。事件流里会留下 clarification_answered 记录，
回放时可见完整的"确认"交互。

答案策略：
  final_confirm / final_confirm_modify  -> "y"（确认查询）
  ask_properties                        -> "全部性质"（极少触发：LLM 未提取到性质）
  human_review_next                     -> "1"（提交裁决，质量管线人工审核兜底）
  human_review_verdict                  -> "1"（采用 Source A，逐条裁决兜底）
  human_review_reason                   -> ""  （回车跳过理由）
  ask_entity                            -> 无法自动（需实体名），记日志等人工
  human_review_custom_value             -> 无法自动（需数值），记日志等人工

用法（后台）:
    python scripts/auto_confirm_runner.py
"""
import io
import json
import sys
import time
from datetime import datetime

import requests

BASE = "http://127.0.0.1:8000"
LOG = "_demo_autoconfirm.log"

ANSWER_MAP = {
    "final_confirm": "y",
    "final_confirm_modify": "y",
    "ask_properties": "全部性质",
    "human_review_next": "1",
    "human_review_verdict": "1",
    "human_review_reason": "",
}
MANUAL_ONLY = ("ask_entity", "human_review_custom_value", "greeting")


def log(line: str) -> None:
    ts = datetime.now().strftime("%m-%d %H:%M:%S")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {line}\n")
    print(f"[{ts}] {line}", flush=True)


def fetch_events(task_id: str) -> list:
    try:
        resp = requests.get(f"{BASE}/api/tasks/{task_id}/events/history", timeout=30)
        resp.raise_for_status()
        return resp.json().get("events", [])
    except Exception as e:
        log(f"events FAIL {task_id[:8]}: {e}")
        return []


def pending_clarification(evs: list):
    """返回等待回答的澄清事件（最后一条 clarification 晚于所有 answered）。"""
    last_clar = None
    last_answered_seq = -1
    for ev in evs:
        t = ev.get("type", "")
        if t == "clarification":
            last_clar = ev
        elif t == "clarification_answered":
            last_answered_seq = max(last_answered_seq, ev.get("seq", 0))
    if last_clar and last_clar.get("seq", 0) > last_answered_seq:
        return last_clar
    return None


def main() -> None:
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    log("auto-confirm runner started")
    while True:
        try:
            resp = requests.get(f"{BASE}/api/tasks?limit=100", timeout=30)
            resp.raise_for_status()
            rows = resp.json().get("items", [])
        except Exception as e:
            log(f"poll FAIL: {e}")
            time.sleep(20)
            continue
        for t in rows:
            if t.get("status") != "running":
                continue
            tid = t["task_id"]
            clar = pending_clarification(fetch_events(tid))
            if not clar:
                continue
            ctype = clar.get("cl_type") or clar.get("title") or "?"
            answer = ANSWER_MAP.get(ctype)
            if answer is None:
                log(f"MANUAL NEEDED {tid[:8]} query={t.get('query','')[:30]!r} clar_type={ctype} — 15min 超时前请人工 resume")
                continue
            try:
                r = requests.post(f"{BASE}/api/tasks/{tid}/resume",
                                  json={"answer": answer}, timeout=30)
                if r.ok:
                    log(f"AUTO-CONFIRM {tid[:8]} [{ctype}] -> {answer!r} ({t.get('query','')[:24]})")
                else:
                    log(f"RESUME FAIL {tid[:8]} [{ctype}] -> {r.status_code} {r.text[:120]}")
            except Exception as e:
                log(f"RESUME EXC {tid[:8]} [{ctype}]: {e}")
        time.sleep(20)


if __name__ == "__main__":
    main()
