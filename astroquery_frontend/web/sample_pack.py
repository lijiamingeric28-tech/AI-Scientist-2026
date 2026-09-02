"""演示样例包导入器（2026-09-02）——内嵌真实查询样例，离线零成本全保真演示。

背景：样例包 sample_pack/（仓库提交，见 scripts/rebuild_sample_pack.py 生成）包含：
- catalog.db：tasks + events 快照（与 web/data/tasks.db 同表结构，VACUUM 后提交）
- figures/<task_id>/**：图证（记录溯源页 + 裁剪图，回放展示与源任务一致所需）
- exports/<task_id[:8]>/**：导出文件（/exports、/export、open-output 指向此处）

回放链路（2026-08-27 事件级重放）的“一模一样”充分条件 = 源任务三件套在场：
任务行（含完整 state_json）+ events + output/ 文件——因为 /records /sources
/figures /quality /exports 等结果端点经 _resolve_source_task 一律指回源任务。
故导入 = 把这三件套装进运行时环境（tasks.db + output/），此后所有既有端点、
回放、历史浏览原样工作，无任何新数据通路。

导入语义（幂等，启动时执行）：
- 同 task_id 行已存在（本机曾真实运行过该查询）→ 仅升级 source='sample'，
  不重建行/事件/文件（内容同源，文件在本地已存在）；若该行事件被清空则补录。
- task_id 不存在（全新克隆/评委机）→ 整行 + events 恢复，缺失文件从包拷贝。
- 样例包不存在（旧版本 checkout / 未运行重建脚本）→ 跳过并记日志，不阻断启动。
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("web")

PACK_DIR_NAME = "sample_pack"
CATALOG_NAME = "catalog.db"


def find_pack_root(*candidates: Path) -> Optional[Path]:
    """返回首个含 catalog.db 的样例包目录；全缺返回 None。"""
    for c in candidates:
        p = Path(c)
        if (p / CATALOG_NAME).is_file():
            return p
    return None


def list_catalog_tasks(pack_root: Path) -> List[Dict[str, Any]]:
    con = sqlite3.connect(str(pack_root / CATALOG_NAME))
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM tasks ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def list_catalog_events(pack_root: Path, task_id: str) -> List[Any]:
    """返回 [(ts, payload JSON 文本), ...]（seq 由导入方自增，剥离源 seq）。"""
    con = sqlite3.connect(str(pack_root / CATALOG_NAME))
    try:
        rows = con.execute(
            "SELECT ts, payload FROM events WHERE task_id=? ORDER BY seq",
            (task_id,),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]
    finally:
        con.close()


def _copy_tree_if_missing(src: Path, dst: Path) -> int:
    """目录级拷贝：目标已存在（非空目录）即跳过，返回拷贝文件数。"""
    if not src.is_dir():
        return 0
    if dst.is_dir() and any(dst.iterdir()):
        return 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(src), str(dst))
    n = sum(1 for _ in src.rglob("*") if _.is_file())
    logger.info("[sample_pack] 拷贝 %s → %s（%d 文件）", src.name, dst, n)
    return n


def import_sample_pack(store: Any, output_root: Path,
                       pack_root: Optional[Path] = None) -> Dict[str, Any]:
    """幂等导入样例包到运行环境。

    Args:
        store: TaskStore（web.main 单例）
        output_root: OUTPUT_DIR（图证/导出落点）
        pack_root: 样例包目录；None 时自动探测（cwd/sample_pack、仓库根）。
    """
    summary: Dict[str, Any] = {
        "pack": None, "imported": 0, "upgraded": 0, "restored_events": 0, "copied": 0,
    }
    # 显式 pack_root 即权威候选（缺失不探测兜底，测试隔离）；None 时探测 cwd/仓库根
    if pack_root is not None:
        candidates = [pack_root]
    else:
        candidates = [
            Path.cwd() / PACK_DIR_NAME,
            Path(__file__).resolve().parent.parent / PACK_DIR_NAME,
        ]
    found = find_pack_root(*(c for c in candidates if c is not None))
    if found is None:
        logger.info("[sample_pack] 未发现样例包（%s）——跳过导入", CATALOG_NAME)
        return summary
    summary["pack"] = str(found)
    try:
        for row in list_catalog_tasks(found):
            task_id = row["task_id"]
            try:
                existing = store.get_task(task_id)
            except Exception:  # noqa: BLE001（老库缺列等极端情形不阻断）
                existing = None
            if existing is not None:
                if (existing.get("source") or "user") != "sample":
                    store.update_task(task_id, source="sample")
                    summary["upgraded"] += 1
                    logger.info("[sample_pack] 升级身份 → sample: %s", task_id)
                # 防御：本机行事件被清理过 → 从包补录（保证回放可用）
                if not store.get_events(task_id, 0):
                    evs = list_catalog_events(found, task_id)
                    if evs:
                        store.restore_events(task_id, evs)
                        summary["restored_events"] += len(evs)
                continue
            # 全新导入：整行 + 事件恢复（状态快照自包，本机改动零影响）
            pdf_paths: List[str] = []
            raw_pdfs = row.get("pdf_paths") or "[]"
            try:
                parsed = json.loads(raw_pdfs) if isinstance(raw_pdfs, str) else raw_pdfs
                if isinstance(parsed, list):
                    pdf_paths = parsed
            except json.JSONDecodeError:
                pdf_paths = []
            store.restore_task(
                task_id, row.get("query") or "",
                title=row.get("title") or "",
                status=row.get("status") or "completed",
                created_at=row.get("created_at"),
                completed_at=row.get("completed_at"),
                output_dir=row.get("output_dir") or "",
                pdf_paths=pdf_paths,
                state_json=row.get("state_json") or "{}",
                replay_of=row.get("replay_of"),
                record_count=row.get("record_count") or 0,
                source_count=row.get("source_count") or 0,
                source="sample",
            )
            evs = list_catalog_events(found, task_id)
            if evs:
                store.restore_events(task_id, evs)
                summary["restored_events"] += len(evs)
            summary["imported"] += 1
            logger.info("[sample_pack] 导入样例任务: %s", task_id)
            # 文件：图证 + 导出目录（本地已存在则跳过拷贝）
            summary["copied"] += _copy_tree_if_missing(
                found / "figures" / task_id, output_root / "figures" / task_id)
            summary["copied"] += _copy_tree_if_missing(
                found / "exports" / (task_id[:8]), output_root / (task_id[:8]))
    except Exception:  # noqa: BLE001 —— 样例导入失败仅告警，绝不阻断服务启动
        logger.exception("[sample_pack] 样例包导入失败")
    logger.info(
        "[sample_pack] 导入完成: pack=%s imported=%d upgraded=%d events=%d copied=%d",
        summary["pack"], summary["imported"], summary["upgraded"],
        summary["restored_events"], summary["copied"],
    )
    return summary
