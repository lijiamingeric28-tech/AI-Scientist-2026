"""
metadata_generation_agent.py — Stage 3: MetadataGenerationAgent

生成字段定义/描述 + 来源汇总 + 处理记录。
LLM: 是 (1 次字段描述生成, 可回退模板)
"""
from __future__ import annotations
import datetime
import json
import re
import time
from typing import Any
from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.tools.export.metadata_generator import generate_metadata
from quality_pipeline.utils.llm import get_llm, set_agent_context, track_raw_llm_call
from quality_pipeline.utils.logger import get_logger
logger = get_logger(__name__)


class MetadataGenerationAgent:
    """Stage 3: 元数据生成 — 字段定义 + LLM 描述"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        export_state = state.get("report_state", {}).get("export", {})
        formatted = export_state.get("formatted_data", {})
        target_schema = state.get("context_state", {}).get("target_schema")
        research_domain = state.get("context_state", {}).get("research_domain", "default")
        wf = state.get("workflow_state", {})
        llm_count = wf.get("llm_call_count", 0)

        # Tool 4: 确定性元数据
        metadata = generate_metadata(
            state.get("data_state", {}).get("current_data", {}),
            target_schema,
            state.get("report_state", {}),
            state.get("context_state", {}),
            wf.get("run_id", ""),
        )

        # ── LLM: 字段描述生成 ──
        field_defs = metadata.get("field_definitions", {})
        try:
            fields_info = []
            for fn, fd in field_defs.items():
                fields_info.append({
                    "name": fn,
                    "semantic_type": fd.get("semantic_type", ""),
                    "unit": fd.get("standard_unit", ""),
                    "criticality": fd.get("criticality", ""),
                })

            set_agent_context("export_etadata")
            llm = get_llm(temperature=0.0)
            prompt = (
                f"You are a {research_domain} data cataloger. "
                f"For each scientific data field below, generate a 1-sentence description "
                f"suitable for a metadata document. Include the standard unit and what the field measures.\n\n"
                f"Fields: {json.dumps(fields_info, indent=2, ensure_ascii=False)}\n\n"
                f"Return JSON: {{\"field_descriptions\": {{\"field_name\": \"description\", ...}}}}"
            )
            resp = llm.invoke([
                {"role": "system", "content": "You are a scientific metadata curator. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ])
            llm_text = resp.content if hasattr(resp, "content") else str(resp)
            m = re.search(r'\{.*\}', llm_text, re.DOTALL)
            if m:
                desc_data = json.loads(m.group(0))
                descriptions = desc_data.get("field_descriptions", {})
                for fn, desc in descriptions.items():
                    if fn in field_defs:
                        field_defs[fn]["description"] = desc
                metadata["field_descriptions_llm"] = True
            llm_count += 1
            track_raw_llm_call(time.time() - t0, agent="export_etadata")
        except Exception as e:
            logger.warning("[MetadataGen] LLM field description failed: %s — using templates", e)
            metadata["field_descriptions_llm"] = False
            for fn, fd in field_defs.items():
                if not fd.get("description"):
                    st = fd.get("semantic_type", fn)
                    unit = fd.get("standard_unit", "")
                    fd["description"] = f"{fn} ({st}), measured in {unit}" if unit else f"{fn} ({st})"

        metadata["field_definitions"] = field_defs

        elapsed = round(time.time() - t0, 3)
        logger.info("[MetadataGen] %d field definitions, LLM=%s, %.2fs",
                    len(field_defs), metadata.get("field_descriptions_llm", False), elapsed)

        return {
            "report_state": {"export": {
                "formatted_data": formatted,
                "organized_data": export_state.get("organized_data", {}),
                "organization_summary": export_state.get("organization_summary", {}),
                "format_issues": export_state.get("format_issues", []),
                "metadata": metadata,
            }},
            "workflow_state": {
                "current_node": "metadata_generation",
                "execution_status": "Success",
                "llm_call_count": llm_count,
                "workflow_history": [{
                    "agent": "MetadataGenerationAgent", "stage": "MetadataGeneration",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"Generated {len(field_defs)} field definitions (LLM={metadata.get('field_descriptions_llm', False)})",
                }],
            },
        }
