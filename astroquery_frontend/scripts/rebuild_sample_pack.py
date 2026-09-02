"""重建演示样例包（2026-09-02）——从本机运行时数据剪出 17 组内嵌样例。

产出（可反复重建，幂等）：
- sample_pack/catalog.db        任务行 + events 快照（与 web/data/tasks.db 同表结构）
- sample_pack/figures/<uuid>/** 图证（记录溯源页 + 裁剪图）
- sample_pack/exports/<8id>/**  导出文件（/exports、/export 端点指向）
- frontend/src/data/samples.json 画廊清单（卡片名/摘要/质量分/记录数，随前端打包）

清单口径：DB 现有 18 行剔除「重放·SN」副本后的 17 条（含 M45 08-28/09-01 双版），
与 docs/demo-query-analysis/最终评委样例集.md 定稿一致。质量分/记录数/来源数从
state_json 按 /quality、/records 同源路径实时取数，不手工抄录。

用法：
    python scripts/rebuild_sample_pack.py            # 全量重建（默认路径自动探测）
    python scripts/rebuild_sample_pack.py --dry-run  # 只核对 17 条齐备性，不写盘
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "web" / "data" / "tasks.db"
OUTPUT_DIR = ROOT / "output"
PACK_DIR = ROOT / "sample_pack"
MANIFEST_PATH = ROOT / "frontend" / "src" / "data" / "samples.json"

# ── 17 条清单（curated 顺序；剔除 30c52db6 重放·SN 副本）─────────────
# key = task_id 前 8 位；name/summary 为人工定稿文案（summary 平实摘要，
# 不写营销词/分类叙事），quality/记录数在重建时从 state_json 实时取数。
SAMPLES: List[Dict[str, str]] = [
    {"id": "e2f0e2a2", "name": "参宿四",
     "summary": "红超巨星：跨 16 年文献提取半径、质量与表面温度，22 条有效温度记录人工复核一致。"},
    {"id": "ead8444c", "name": "大角星",
     "summary": "K 巨星：距离、金属丰度与有效温度四类记录（含视差 8 条）互相印证，复核无错。"},
    {"id": "7177a745", "name": "Pollux",
     "summary": "K0 巨星完整画像：质量、半径、表面温度与光谱型四性质齐全，16 条记录全部干净。"},
    {"id": "5db879b9", "name": "天狼星 B",
     "summary": "白矮星简并物理：质量 21 条记录最完整，连同表面重力与冷却年龄，3.2% 误差率全部可溯源。"},
    {"id": "655cd7af", "name": "天鹅座 X-1",
     "summary": "黑洞双星：轨道周期 26 条、致密天体质量 22 条，呈现 8.7→21.2 太阳质量的测定史。"},
    {"id": "4875820b", "name": "δ Cephei",
     "summary": "造父变星：光变周期、距离与视差记录跨文献高度一致（周期 16 条），含金属丰度。"},
    {"id": "d888fd23", "name": "比邻星",
     "summary": "近邻恒星测量代表：视差 768 mas 等记录极准，距离、视差、自行三类相互印证。"},
    {"id": "1e6c3e2e", "name": "昴星团 M45（08-28 版）",
     "summary": "昴星团距离争议史整理：年龄、距离与金属丰度，双口径对比完整呈现。"},
    {"id": "4873c876", "name": "昴星团 M45（09-01 版）",
     "summary": "旗舰样例复跑：距离、年龄、金属丰度五性质 103/111 条记录跨口径一致，Hipparcos 争议史完整。"},
    {"id": "da7eff2b", "name": "半人马座 ω",
     "summary": "球状星团：金属丰度 11 条、总质量 8 条与中心速度弥散 6 条，三性质互证。"},
    {"id": "4f1eba75", "name": "五车二 Capella",
     "summary": "双星：轨道周期 104.02 天精确测定（12 条），双星质量与视向速度半振幅复核一致。"},
    {"id": "136c2238", "name": "M87",
     "summary": "活动星系核：中央黑洞质量 30 条记录综合 EHT/Keck 等五类方法，另含爱丁顿比与 6cm 射电流量。"},
    {"id": "67eafb42", "name": "NGC 4151",
     "summary": "赛弗特 1 星系宽线区：Hβ 宽线 37 条、黑洞质量 25 条与 X 射线光子谱指数，99 条记录全库最大。"},
    {"id": "57c94f31", "name": "3C 273",
     "summary": "耀变体：红移 8 条与绝对星等 4 条，补录后全记录干净，适合演示星系尺度参数。"},
    {"id": "7657f951", "name": "HD 209458b",
     "summary": "系外行星：轨道周期、行星质量与行星半径三性质，45 条记录复核无错（类太阳恒星的凌星行星）。"},
    {"id": "0eab300f", "name": "后发座星系团",
     "summary": "星系团：MCXC 与 PSZ2 多库命中，M500 质量 9 条、X 射线温度与速度弥散齐备。"},
    {"id": "36529ff4", "name": "SN 2011fe",
     "summary": "Ia 型超新星：峰值绝对星等多波段口径 32 条记录，质量分 0.955，修复版（含人工复核验证）。"},
]


def _state_of(con: sqlite3.Connection, task_id: str) -> Dict[str, Any]:
    row = con.execute("SELECT state_json FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    if not row or not row[0]:
        return {}
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return {}


def _sample_stats(state: Dict[str, Any]) -> Dict[str, Any]:
    """质量分/记录数/来源数 —— 与 /quality、/records 端点同源路径。"""
    qr = (state.get("final_output") or {}).get("quality_report") or {}
    score = (qr.get("report_state") or {}).get("quality", {}).get("quality_scoring", {}).get("overall_score")
    sd = (qr.get("output_state") or {}).get("structured_data") or {}
    row_count = sd.get("row_count")
    recs = (sd.get("json") or {}).get("records")
    srcs = (sd.get("json") or {}).get("sources")
    return {
        "quality_score": round(float(score), 4) if isinstance(score, (int, float)) else None,
        "record_count": int(row_count) if isinstance(row_count, (int, float)) else len(recs or []),
        "source_count": len(srcs) if isinstance(srcs, (list, dict)) else 0,
    }


def collect() -> List[Dict[str, Any]]:
    """核对 17 条齐备性并采集展示数据（不写盘）。失败时抛 RuntimeError。"""
    if not DB_PATH.is_file():
        raise RuntimeError(f"任务库不存在: {DB_PATH}（请先跑过真实查询）")
    con = sqlite3.connect(str(DB_PATH))
    try:
        con.row_factory = sqlite3.Row
        by_short: Dict[str, Any] = {}
        for row in con.execute("SELECT * FROM tasks"):
            by_short[row["task_id"][:8]] = dict(row)
        out: List[Dict[str, Any]] = []
        for s in SAMPLES:
            row = by_short.get(s["id"])
            if not row:
                raise RuntimeError(f"样例缺失: {s['id']}（{s['name']}）——请先完成该真实查询")
            n_ev = con.execute("SELECT COUNT(*) FROM events WHERE task_id=?", (row["task_id"],)).fetchone()[0]
            if n_ev == 0:
                raise RuntimeError(f"样例无事件（不可回放）: {row['task_id'][:8]} {s['name']}")
            fig_dir = OUTPUT_DIR / "figures" / row["task_id"]
            if not fig_dir.is_dir() or not any(fig_dir.iterdir()):
                raise RuntimeError(f"样例图证缺失: {fig_dir}（回放展示需图证文件）")
            stats = _sample_stats(_state_of(con, row["task_id"]))
            out.append({
                "name": s["name"],
                "summary": s["summary"],
                "task_id": row["task_id"],
                "title": row.get("title") or "",
                "query": row.get("query") or "",
                "quality_score": stats["quality_score"],
                "record_count": stats["record_count"],
                "source_count": stats["source_count"],
            })
        return out
    finally:
        con.close()


def _png_to_webp_bytes(src: Path) -> bytes:
    """PNG → WebP(q85) 压缩（图证截图类约省 60-75%）；Pillow 依赖。"""
    from PIL import Image
    im = Image.open(str(src)).convert("RGB")
    buf = BytesIO()
    im.save(buf, "WEBP", quality=85)
    return buf.getvalue()


def _copy_figures_webp(src: Path, dst: Path) -> int:
    """拷贝图证目录并把 PNG 转为同名 .webp（保留子目录结构，如 source_pages/bibcode/）。"""
    from PIL import Image
    n = 0
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(src)
        out_path = dst / (rel.with_suffix(".webp") if f.suffix.lower() == ".png" else rel)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if f.suffix.lower() == ".png":
            im = Image.open(str(f)).convert("RGB")
            im.save(str(out_path), "WEBP", quality=85)
            n += 1
        else:
            shutil.copy2(str(f), str(out_path))
    return n


def _webpify_state(state_json: str) -> str:
    """state_json 中 figure_evidence[].image_path 引用同步 .png→.webp
    （/figures 端点按 image_path 文件名拼 URL——引用必须与落盘文件一致）。"""
    def repl(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: (val[:-4] + ".webp" if (k == "image_path"
                    and isinstance(val, str) and val.endswith(".png")) else repl(val))
                    for k, val in v.items()}
        if isinstance(v, list):
            return [repl(x) for x in v]
        return v
    return json.dumps(repl(json.loads(state_json)), ensure_ascii=False, default=str)


def build_pack(items: List[Dict[str, Any]]) -> None:
    """写 catalog.db + 拷 figures/exports + 写前端清单（幂等，可重复执行）。"""
    ids = [it["task_id"] for it in items]
    if PACK_DIR.exists():
        shutil.rmtree(str(PACK_DIR))  # 整体重建，避免残留旧任务目录
    (PACK_DIR / "figures").mkdir(parents=True)
    (PACK_DIR / "exports").mkdir(parents=True)

    # catalog.db：TaskStore 同构表（restore_task/restore_events 走任务存储的锁与序列化）
    sys.path.insert(0, str(ROOT))
    from web.task_store import TaskStore  # 本机任务库的并发写入与样例包隔离

    cat = TaskStore(PACK_DIR / "catalog.db")
    con = sqlite3.connect(str(DB_PATH))
    try:
        con.row_factory = sqlite3.Row
        copied_fig = copied_exp = 0
        for it in items:
            tid = it["task_id"]
            row = dict(con.execute("SELECT * FROM tasks WHERE task_id=?", (tid,)).fetchone())
            pdfs = row.get("pdf_paths") or "[]"
            try:
                pdf_list = json.loads(pdfs) if isinstance(pdfs, str) else pdfs
            except json.JSONDecodeError:
                pdf_list = []
            cat.restore_task(
                tid, row["query"], title=row["title"] or "", status=row["status"],
                created_at=row["created_at"], completed_at=row["completed_at"],
                output_dir=row.get("output_dir") or "", pdf_paths=pdf_list,
                # 2026-09-02：图片转 WebP 后，state 内 image_path 引用同步 .png→.webp
                state_json=_webpify_state(row.get("state_json") or "{}"),
                replay_of=row.get("replay_of"),
                record_count=row.get("record_count") or 0, source_count=row.get("source_count") or 0,
                source="sample",
            )
            evs = [(r["ts"], r["payload"]) for r in con.execute(
                "SELECT ts, payload FROM events WHERE task_id=? ORDER BY seq", (tid,))]
            cat.restore_events(tid, evs)
            # 文件（图证按任务全 uuid；导出按 run_id=前 8 位 —— 与 /figures、/exports 端点落点一致）
            # 2026-09-02：图证拷贝时 PNG→WebP(q85) 压缩（200MB → ~60MB）
            fig_src = OUTPUT_DIR / "figures" / tid
            if fig_src.is_dir():
                _copy_figures_webp(fig_src, PACK_DIR / "figures" / tid)
                copied_fig += 1
            exp_src = OUTPUT_DIR / tid[:8]
            if exp_src.is_dir():
                shutil.copytree(str(exp_src), str(PACK_DIR / "exports" / tid[:8]))
                copied_exp += 1
    finally:
        con.close()

    # 前端画廊清单（单一数据源，随 bundle 打包）
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "由 scripts/rebuild_sample_pack.py 生成——质量分/记录数取自任务 state_json（与结果端点同源），勿手工编辑",
        "samples": items,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"[rebuild] 样例包完成: {PACK_DIR}（{len(items)} 条）")
    print(f"[rebuild] 图证目录 {copied_fig}/{len(items)} · 导出目录 {copied_exp}/{len(items)}")
    print(f"[rebuild] 前端清单 → {MANIFEST_PATH}（{MANIFEST_PATH.stat().st_size/1024:.0f} KB）")


def main() -> int:
    ap = argparse.ArgumentParser(description="重建演示样例包（17 条内嵌样例）")
    ap.add_argument("--dry-run", action="store_true", help="只核对 17 条齐备性与分数取数，不写盘")
    args = ap.parse_args()
    try:
        items = collect()
    except RuntimeError as e:
        print(f"[rebuild] 校验失败: {e}", file=sys.stderr)
        return 1
    for it in items:
        print(f"  {it['task_id'][:8]}  {it['name']:<16} "
              f"质量 {it['quality_score'] or '-':<7} 记录 {it['record_count']:<4} 来源 {it['source_count']}")
    if args.dry_run:
        print(f"[rebuild] dry-run: 17 条齐备（{len(items)}），未写盘")
        return 0
    build_pack(items)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
