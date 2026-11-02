"""复现 7601ee09 任务的质量管线 RecursionError，DEBUG 级别打印完整堆栈。

用已完成任务的状态快照直接跑 quality_pipeline，避免重跑 26 分钟完整任务。
"""
import json
import logging
import os
import sqlite3
import sys
import traceback

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s %(message)s")

os.chdir(r"E:\work\AI-Scientist-2026\astroquery_frontend")
sys.path.insert(0, ".")

conn = sqlite3.connect("web/data/tasks.db")
row = conn.execute(
    "SELECT state_json FROM tasks WHERE task_id='7601ee09-78a3-47d8-9779-db4630489f91'"
).fetchone()
state = json.loads(row[0])
final_output = state.get("final_output") or {}
property_spec = state.get("property_spec") or []
print(f"records={len(final_output.get('records') or [])} sources={len(final_output.get('sources') or [])}")

from astroquery_ai.config import get_settings  # noqa: E402
from astroquery_ai.quality_adapter import (  # noqa: E402
    generate_standard_units,
    generate_target_schema,
)
from quality_pipeline.configs import set_research_domain  # noqa: E402
from quality_pipeline.graph import build_quality_graph  # noqa: E402
from quality_pipeline.quality_state import make_initial_state  # noqa: E402

domain = get_settings().default_research_domain
initial = make_initial_state(final_output, run_id="repro")
initial["context_state"]["target_schema"] = generate_target_schema(property_spec)
initial["context_state"]["standard_units"] = generate_standard_units(property_spec)
initial["context_state"]["research_domain"] = domain
initial["context_state"]["query_id"] = "repro"
set_research_domain(domain)

print(f"=== 开始复现（research_domain={domain}）===")
graph = build_quality_graph().compile()
try:
    result = graph.invoke(initial)
    print("=== 复现完成，未报错 ===")
    qr = result.get("quality_report") or {}
    print("quality_report 键:", list(qr.keys())[:15])
except RecursionError:
    print("=== 复现命中 RecursionError ===")
    traceback.print_exc()
except Exception as exc:
    print(f"=== 复现异常（非 RecursionError）: {type(exc).__name__}: {exc} ===")
    traceback.print_exc()
