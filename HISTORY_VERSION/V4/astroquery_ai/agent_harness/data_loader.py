"""任务已沉淀数据安全加载器与索引构建器 (Task Data Loader)
调阅 tasks.db (state_json)、output/ 导出文件及 figures 多模态图证缓存，
支持 replay_of 回放映射与缺省安全回退。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_harness.data_loader")


class TaskDataBundle:
    """封装单一任务的全部沉淀资产与极速检索索引。"""

    def __init__(self, task_id: str, raw_task: Dict[str, Any], state: Dict[str, Any], output_dir: Path):
        self.task_id = task_id
        self.raw_task = raw_task
        self.state = state
        self.output_dir = output_dir

        self.query = raw_task.get("query", "")
        self.title = raw_task.get("title", "")
        self.target_entity = state.get("target_entity") or state.get("simbad_info", {}).get("main_id") or ""
        self.requested_properties = state.get("requested_properties") or []

        # 核心数据切片
        fo = state.get("final_output") or {}
        qr = fo.get("quality_report") or state.get("quality_report") or {}

        # 1. 结构化记录 (优先取 quality_report.output_state.structured_data.json.records)
        self.records: List[Dict[str, Any]] = (
            qr.get("output_state", {}).get("structured_data", {}).get("json", {}).get("records")
            or fo.get("records")
            or []
        )

        # 2. 文献来源
        self.sources: List[Dict[str, Any]] = (
            qr.get("output_state", {}).get("structured_data", {}).get("json", {}).get("sources")
            or fo.get("sources")
            or []
        )

        # 3. 多模态图证
        self.figures: List[Dict[str, Any]] = fo.get("figure_evidence") or state.get("figure_evidence") or []

        # 4. 质量与冲突状态
        rs = qr.get("report_state") or {}
        self.quality = rs.get("quality") or {}
        self.conflict = rs.get("conflict") or []
        self.insights = rs.get("insights") or {}
        self.normalization = rs.get("normalization") or {}

        # 展平冲突项（字典结构与列表结构通用兼容）
        self.conflict_items: List[Dict[str, Any]] = []
        if isinstance(self.conflict, dict):
            vars_list = self.conflict.get("aggregation", {}).get("variances") or []
            anoms_list = self.conflict.get("resolution_report", {}).get("anomalies") or []
            self.conflict_items = list(vars_list) + list(anoms_list)
        elif isinstance(self.conflict, list):
            self.conflict_items = list(self.conflict)

        # 5. 字段级溯源追踪
        ds = qr.get("data_state") or {}
        self.data_trace: List[Dict[str, Any]] = ds.get("data_trace") or []

        # 内存索引加速
        self._build_indexes()

    def _build_indexes(self) -> None:
        self.records_by_id: Dict[str, Dict[str, Any]] = {}
        self.records_by_prop: Dict[str, List[Dict[str, Any]]] = {}
        for r in self.records:
            rid = str(r.get("record_id") or "")
            if rid:
                self.records_by_id[rid] = r
            p = str(r.get("field_name") or r.get("property_name") or "").strip().lower()
            if p:
                self.records_by_prop.setdefault(p, []).append(r)

        self.sources_by_bibcode: Dict[str, Dict[str, Any]] = {}
        for s in self.sources:
            b = str(s.get("source_id") or s.get("bibcode") or "").strip()
            if b:
                self.sources_by_bibcode[b] = s

        self.figures_by_id: Dict[str, Dict[str, Any]] = {}
        for f in self.figures:
            img_p = f.get("image_path", "")
            stem = Path(img_p).stem if img_p else ""
            fid = f.get("figure_id") or f.get("id") or stem or f"{f.get('source_id')}_p{f.get('page')}_f{f.get('figure_index')}"
            fid = str(fid).strip()
            if fid:
                f["figure_id"] = fid  # 规范化回填
                self.figures_by_id[fid] = f

        self.conflicts_by_field: Dict[str, List[Dict[str, Any]]] = {}
        for c in self.conflict_items:
            fld = str(c.get("field_name") or c.get("field") or "").strip().lower()
            if fld:
                self.conflicts_by_field.setdefault(fld, []).append(c)

        self.trace_by_record_id: Dict[str, List[Dict[str, Any]]] = {}
        for t in self.data_trace:
            rid = str(t.get("record_id") or "")
            if rid:
                self.trace_by_record_id.setdefault(rid, []).append(t)

    def get_summary_context(self) -> str:
        """为智能体生成极简任务基底事实文本（Tier 1 Grounded Context）。"""
        props_str = "、".join(self.requested_properties) if self.requested_properties else "多项物理量"
        score = self.quality.get("quality_scoring", {}).get("overall_score")
        score_str = f"{score * 100:.1f} / 100" if score is not None else "尚无综合评分"
        return (
            f"【当前任务基底事实】\n"
            f"- 目标天体: {self.target_entity or '天体目标'}\n"
            f"- 初始需求: {self.query}\n"
            f"- 检索性质: {props_str}\n"
            f"- 缓存体量: 整理出 {len(self.records)} 条规范化测量记录，来自 {len(self.sources)} 篇文献，包含 {len(self.figures)} 幅多模态图证\n"
            f"- 质检总评分: {score_str}\n"
            f"- 冲突仲裁案卷: 共计 {len(self.conflict_items)} 组字段级交叉争议与异常分析"
        )


def load_task_bundle(task_id: str, db_path: Optional[str | Path] = None, output_dir: Optional[str | Path] = None) -> TaskDataBundle:
    """加载任务数据包，支持回放穿透与路径推断。"""
    root_dir = Path(__file__).resolve().parent.parent.parent
    if db_path is None:
        db_path = root_dir / "web" / "data" / "tasks.db"
        if not db_path.exists():
            sample_db = root_dir / "sample_pack" / "catalog.db"
            if sample_db.exists():
                db_path = sample_db

    if output_dir is None:
        output_dir = root_dir / "output"
        if not output_dir.exists():
            output_dir = root_dir / "sample_pack"

    db_path = Path(db_path)
    output_dir = Path(output_dir)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            # 尝试在 sample_pack/catalog.db 找
            sample_db = root_dir / "sample_pack" / "catalog.db"
            if sample_db.exists() and sample_db != db_path:
                conn2 = sqlite3.connect(str(sample_db))
                conn2.row_factory = sqlite3.Row
                try:
                    row = conn2.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
                finally:
                    conn2.close()

        if not row:
            raise ValueError(f"Task not found: {task_id}")

        raw_task = dict(row)
        # 若是回放任务，追溯到源任务
        source_task_id = raw_task.get("replay_of") or task_id
        if source_task_id != task_id:
            src_row = cur.execute("SELECT * FROM tasks WHERE task_id=?", (source_task_id,)).fetchone()
            if src_row:
                raw_task = dict(src_row)
                task_id = source_task_id

        state_str = raw_task.get("state_json") or "{}"
        try:
            state = json.loads(state_str)
        except Exception:
            state = {}

        return TaskDataBundle(task_id, raw_task, state, output_dir)
    finally:
        conn.close()
