"""Hybrid Document Grounder — 混合 bbox 定位器 (2026-08-24)

背景: 原方案用 100 DPI 整页图 + qwen3.7-flash 直接输出 bbox, 实测
(98 条 M45 记录 vs PyMuPDF 文本层真值): IoU 中位数 0.00, ≥0.5 仅 2%,
59% 框中心偏差 >3 倍真值宽度 — 密集小文本在 VLM 视觉 Patch 分辨率下
无法精确定位, 且每条记录一次 API 调用 (限流 + 成本)。

方案 (分级漏斗, 向量优先 → 视觉裁剪兜底 → 段落降级, 零数据丢弃):
  Level 1 矢量定位 (PyMuPDF 文本层): 数值候选形态匹配 + 上下文空间消歧,
            <2ms/条, 0 API 成本, 字体级精度 — 预期覆盖 85%+;
  Level 2 裁剪放大 (200-300 DPI 局部高清图 + qwen3.7-flash): 仅 Level 1
            未命中时触发, 局部文字像素高度放大 3-4 倍后再视觉定位;
  Level 3 兜底 (上下文段落框): 绝不丢弃数据, 返回段落级近似框并标注
            bbox_source="fallback", 前端/下游可区分样式。
"""
from __future__ import annotations

import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

import fitz  # PyMuPDF

from .logger import get_logger

logger = get_logger(__name__)

# 归一化 0-1000 (与下游 bbox_coord_system="normalized_1000" 契约一致)
NORM = 1000.0


def _norm_text(s: str) -> str:
    """文本归一: 全角→半角, 兼容字符统一, 空白折叠 (提高 PDF 文本层命中率)。"""
    s = unicodedata.normalize("NFKC", str(s))
    s = s.replace("−", "-").replace("–", "-").replace("·", ".")  # 数学负号/中点
    return " ".join(s.split())


def _try_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _value_candidates(field_value, field_unit: str = "") -> List[str]:
    """生成数值在文本层的候选形态 (按优先级: 完整写法 → 数值 → 紧凑写法 → 排版变体)。

    覆盖真实论文排版差异:
      - 负号变体 (连字符 - vs 数学负号 − U+2212)
      - 科学计数法 (1.25e8 → 1.25×108 / 1.25 × 108 / 1.25×10^8, 上标 8 在
        文本层就是普通字符)
      - 带符号值 (文本层可能把符号写在标签里, 数值本体不带符号)
    """
    full = _norm_text(f"{field_value} {field_unit}".strip()) if field_unit else _norm_text(str(field_value))
    cands: List[str] = []
    if full:
        cands.append(full)
        cands.append(full.replace(" ", ""))  # 紧凑排版 "134.6±3.1"
        if "-" in full:
            cands.append(full.replace("-", "−"))  # 数学负号变体
        if "−" in full:
            cands.append(full.replace("−", "-"))
    # 数值本体 (科学计数法/小数/整数; 负号)
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", full)
    if m and m.group(0) not in cands:
        cands.append(m.group(0))
    # 无符号数值 (符号可能在标签/列名中)
    m_abs = re.search(r"\d*\.?\d+(?:[eE][-+]?\d+)?", full)
    if m_abs and m_abs.group(0) not in cands:
        cands.append(m_abs.group(0))
    # 科学计数法排版展开: 1.25e8 → 1.25×108 / 1.25 × 108 / 1.25×10^8
    m_sci = re.search(r"([+-]?\d*\.?\d+)[eE]([+-]?\d+)", full)
    if m_sci:
        mant, exp = m_sci.group(1), m_sci.group(2)
        for fmt in (f"{mant}×10{exp}", f"{mant} × 10{exp}",
                    f"{mant}×10^{exp}", f"{mant} × 10^{exp}",
                    f"{mant}× 10{exp}"):
            if fmt not in cands:
                cands.append(fmt)
    # 时间单位等价形态: VLM 常把 "125 Myr" 转写为 125000000 yr —
    # 大数 yr/科学计数 yr 补充 Myr/Gyr 写法 (含 ± 误差串的双数转换)
    _TIME_UNITS = {"yr", "year", "years", "Myr", "Gyr"}
    if field_unit in _TIME_UNITS:
        def _fmt(n: float) -> str:
            if abs(n) >= 1e6 and n == int(n):
                return str(int(n))
            return f"{n:g}"
        def _to_alt(num_str: str, div: float, suffix: str) -> str:
            try:
                v = float(num_str)
                return f"{_fmt(v / div)} {suffix}"
            except ValueError:
                return ""
        num_alts: List[str] = []
        for num_str in re.findall(r"[+-]?\d*\.?\d+(?:[eE][+-]?\d+)?", full):
            v = _try_float(num_str)
            if v is None:
                continue
            alts: List[str] = []
            if field_unit in {"yr", "year", "years"} and abs(v) >= 1e5:
                for div, suf in ((1e6, "Myr"), (1e9, "Gyr")):
                    alt = _to_alt(num_str, div, suf)
                    if alt and alt not in cands:
                        cands.append(alt)
                    alt_tight = alt.replace(" ", "")
                    if alt_tight not in cands:
                        cands.append(alt_tight)
                    if alt:
                        alts.append(alt)
            elif field_unit == "Myr" and abs(v) >= 1e3:
                alt = _to_alt(num_str, 1e3, "Gyr")
                if alt and alt not in cands:
                    cands.append(alt)
                if alt:
                    alts.append(alt)
            if alts:
                num_alts.append(alts[0])
        # 多数值 (带 ± 误差) 组合形态: "1.2e8 ± 2e7" → "120 ± 20 Myr"
        if len(num_alts) >= 2:
            combined = f"{num_alts[0]} ± {num_alts[1]}"
            if combined not in cands:
                cands.append(combined)
    return [c for c in cands if c]


def _context_candidates(context_snippet: str) -> List[str]:
    """上下文片段候选 (整段 → 逐级截短, 兼容连字/换行拆分导致的匹配失败)。"""
    ctx = _norm_text(context_snippet)
    cands = []
    for n in (48, 36, 28, 20):
        if len(ctx) > n:
            cands.append(ctx[:n])
    cands.append(ctx)
    return [c for c in dict.fromkeys(cands) if c]


def _search_first(page: fitz.Page, text: str) -> Optional[fitz.Rect]:
    hits = page.search_for(text)
    return hits[0] if hits else None


def _locate_context(page: fitz.Page, context_snippet: str) -> Optional[fitz.Rect]:
    """定位上下文片段在页面的位置 (逐级截短候选, 返回第一个命中)。"""
    if not context_snippet:
        return None
    for cand in _context_candidates(context_snippet):
        r = _search_first(page, cand)
        if r:
            return r
    return None


def _locate_value_vector(
    page: fitz.Page,
    field_value,
    field_unit: str,
    context_snippet: str,
) -> Tuple[Optional[fitz.Rect], int]:
    """矢量层定位数值: 候选形态逐一搜索, 多命中时按上下文空间距离消歧。

    Returns: (rect, num_hits) — rect=None 表示未命中。
    """
    ctx_rect = _locate_context(page, context_snippet)
    ctx_cy = ((ctx_rect.y0 + ctx_rect.y1) / 2.0) if ctx_rect else None

    # 跨候选 argmin: 每个候选形态取"距上下文最近"的命中, 再横向比较 —
    # 首个候选短路会选到别处唯一命中的错误行 (如 "134.8 pc" 在他行
    # 唯一命中, 而纯数值 "134.8" 恰在上下文行); 无上下文时取首个命中。
    best_rect = None
    best_dist = None
    best_hits = 0
    for cand in _value_candidates(field_value, field_unit):
        hits = page.search_for(cand)
        if not hits:
            continue
        if ctx_cy is not None:
            rect = min(hits, key=lambda r: abs((r.y0 + r.y1) / 2.0 - ctx_cy))
            dist = abs((rect.y0 + rect.y1) / 2.0 - ctx_cy)
        else:
            rect, dist = hits[0], 0.0
        if best_rect is None or dist < best_dist:
            best_rect, best_dist, best_hits = rect, dist, len(hits)
    if best_rect is None:
        return None, 0
    return best_rect, best_hits


def _rect_to_norm(rect: fitz.Rect, page: fitz.Page, pad: float = 2.0) -> List[int]:
    """PDF 点坐标 → 归一化 0-1000 (轻量外扩避免贴边)。"""
    w, h = page.rect.width, page.rect.height
    return [
        max(0, int((rect.x0 - pad) / w * NORM)),
        max(0, int((rect.y0 - pad) / h * NORM)),
        min(int(NORM), int((rect.x1 + pad) / w * NORM)),
        min(int(NORM), int((rect.y1 + pad) / h * NORM)),
    ]


# ══════════════════════════════════════════════════════════════
# Level 1: 矢量定位
# ══════════════════════════════════════════════════════════════

@lru_cache(maxsize=64)
def _open_pdf(pdf_path: str) -> Optional[fitz.Document]:
    """PDF 打开缓存 (每 worker 线程内 lru_cache, 避免重复 IO)。"""
    try:
        return fitz.open(pdf_path)
    except Exception as e:  # noqa: BLE001 — 打开失败走视觉兜底
        logger.warning("[HybridGrounder] PDF open failed %s: %s", pdf_path, e)
        return None


def ground_via_vector(pdf_path: str, page_no: int, field_value, field_unit: str,
                      context_snippet: str) -> Optional[dict]:
    """Level 1: PyMuPDF 矢量文本层定位。

    Returns: {"bbox_2d": [...], "source": "vector", "confidence": 1.0, "num_hits": n}
             未命中返回 None (调用方走 Level 2)。
    """
    doc = _open_pdf(pdf_path)
    if doc is None or page_no < 1 or page_no > len(doc):
        return None
    try:
        page = doc[page_no - 1]
        rect, num_hits = _locate_value_vector(page, field_value, field_unit, context_snippet)
        if rect is None or rect.width < 0.5 or rect.height < 0.5:
            return None
        # 宽高比 sanity: 数值框不应是整行/整段 (防 search 命中含该子串的长串)
        if rect.width > 60 and rect.height > 40:
            return None
        bbox = _rect_to_norm(rect, page)
        return {
            "bbox_2d": bbox,
            "bbox_source": "vector",
            "confidence": 1.0,
            "found": True,
            "num_hits": num_hits,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("[HybridGrounder] vector grounding failed p%s: %s", page_no, e)
        return None


# ══════════════════════════════════════════════════════════════
# 表格轨: 宏定位 (整表框, 表头 + 表体 + 底注)
# ══════════════════════════════════════════════════════════════

_TABLE_NO_RE = re.compile(r"Table\s*(\d+)", re.IGNORECASE)


def _detect_table_body(page: fitz.Page, caption_rect: fitz.Rect,
                       max_gap: float = 20.0, max_height_frac: float = 0.62) -> Optional[fitz.Rect]:
    """标题下方的连续词区 = 表格体 (含数据行与紧跟的 Note 底注)。

    逻辑: 收集标题下方、横向宽范围内的所有词; 按 y 排序从标题底边开始
    吞并, 直到出现 > max_gap 的纵向间隙 (表格与正文之间的空行)。
    横向取 [页左页边距, 页右页边距] 全宽 (居中标题的表格从左页边距
    开始; 全宽表格横跨双栏); 跨度失控 (> 页高 62%) 时竖向截断 —
    横向收窄会把全宽表格右半裁掉, 是错误方向。

    Returns: 表格体矩形 (不含标题), 失败返回 None。
    """
    words = page.get_text("words")
    if not words:
        return None
    page_w, page_h = page.rect.width, page.rect.height

    def _span(x0: float, x1: float):
        below = [w for w in words
                 if w[3] >= caption_rect.y1 - 2 and x0 <= w[0] and w[2] <= x1]
        if not below:
            return None
        below.sort(key=lambda w: (w[1], w[0]))
        cur_bottom = caption_rect.y1
        picked = []
        for w in below:
            # 只做纵向间隙切割 (同行词必须全部纳入, 否则框宽丢失)
            if w[1] - cur_bottom > max_gap:
                break
            picked.append(w)
            cur_bottom = max(cur_bottom, w[3])
        if not picked:
            return None
        return fitz.Rect(
            min(w[0] for w in picked), caption_rect.y1,
            max(w[2] for w in picked), cur_bottom,
        )

    # 全宽: 左到页面左页边距 (居中标题场景), 右到右页边距
    wide = _span(min(caption_rect.x0 - 25, 50), page_w - 25)
    if wide is None:
        return None
    # 跨度失控 (表格后无大间隙, 底注/正文被连续吞并) → 竖向截断保 x 全宽
    if wide.height > max_height_frac * page_h:
        wide = fitz.Rect(wide.x0, wide.y0, wide.x1,
                         caption_rect.y1 + max_height_frac * page_h)
    return wide


def ground_table_vector(pdf_path: str, page_no: int, context_snippet: str) -> Optional[dict]:
    """表格数据宏定位: 表标题锚定 + find_tables 几何并集 (0 成本, 整表框)。

    表格单元格级定位既难 (VLM 小数字漂移) 又低价值 (用户核验需要整表
    上下文), 故表格数据直接框"标题 + 表体 + 数据行"整张表, 与前端
    大框样式配合形成证据卡片。

    Returns: {"bbox_2d", "bbox_source": "full_table", "confidence", "table_no"}
    """
    doc = _open_pdf(pdf_path)
    if doc is None or page_no < 1 or page_no > len(doc):
        return None
    try:
        page = doc[page_no - 1]

        # 1. 表标题候选 (context 必含 "Table N" — 提取协议保证)。
        #    上下文命中候选硬优先: 其余 "Table N" 出现处可能是正文内联
        #    引用 (下方无表格或表格更远), 仅当上下文候选无表格体时才
        #    退而考虑其他候选。
        m = _TABLE_NO_RE.search(context_snippet)
        ctx_cap = _locate_context(page, context_snippet) if m else None
        alts: List[fitz.Rect] = []
        if m:
            for pat in (f"Table {m.group(1)}.", f"Table {m.group(1)}:",
                        f"Table {m.group(1)}"):
                hits = page.search_for(pat)
                for h in hits[:4]:
                    if ctx_cap is None or abs(h.y0 - ctx_cap.y0) > 4:
                        if h not in alts:
                            alts.append(h)

        # 2. 上下文候选硬优先 (标题与表格间大间隙时以 45pt 重试一次)
        best_caption = None
        best_body = None
        if ctx_cap is not None:
            body = _detect_table_body(page, ctx_cap)
            if body is None or body.height < 20:
                body = _detect_table_body(page, ctx_cap, max_gap=45)
            if body is not None and body.height >= 20:
                best_caption, best_body = ctx_cap, body
        if best_body is None:
            for cap in alts[:4]:
                body = _detect_table_body(page, cap)
                if body is None or body.height < 20:
                    continue
                if best_body is None or body.get_area() > best_body.get_area():
                    best_caption, best_body = cap, body

        if best_caption is None and best_body is None:
            return None

        if best_caption is not None and best_body is not None:
            rect = fitz.Rect(
                min(best_caption.x0, best_body.x0), best_caption.y0,
                max(best_caption.x1, best_body.x1), best_body.y1,
            )
        elif best_body is not None:
            rect = best_body
        else:
            # 标题命中但表格体检测失败: 标题向下扩展 260pt 作近似整表区
            rect = fitz.Rect(
                best_caption.x0, best_caption.y0,
                page.rect.width, min(page.rect.height, best_caption.y1 + 260),
            )

        bbox = _rect_to_norm(rect, page, pad=2)
        return {
            "bbox_2d": bbox,
            "bbox_source": "full_table",
            "confidence": 1.0 if best_body is not None else 0.6,
            "found": True,
            "table_no": int(m.group(1)) if m else None,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("[HybridGrounder] table vector grounding failed p%s: %s", page_no, e)
        return None


# ══════════════════════════════════════════════════════════════
# Level 2: 高清裁剪 + VLM 局部重定位
# ══════════════════════════════════════════════════════════════

def render_crop(pdf_path: str, page_no: int, around: Optional[fitz.Rect] = None,
                zoom: float = 300.0 / 72.0):
    """渲染局部高清裁剪图 (300 DPI)。

    around 为上下文命中区时非对称外扩: 数值通常出现在上下文下方
    (表格标题→数据行/正文行), 向下扩展 220pt, 其余方向 100pt;
    around=None 时渲染整页 (200 DPI 兜底)。返回 (PIL.Image, crop_rect)。
    """
    from PIL import Image
    import io

    doc = _open_pdf(pdf_path)
    if doc is None:
        return None, None
    page = doc[page_no - 1]
    if around is None:
        zoom = 200.0 / 72.0
        clip = page.rect
    else:
        clip = fitz.Rect(
            max(0, around.x0 - 100),
            max(0, around.y0 - 30),
            min(page.rect.width, around.x1 + 100),
            min(page.rect.height, around.y1 + 220),
        )
        # 裁剪区过小 (表格单元格级) 时扩大, 保证 VLM 有足够上下文
        if clip.width < 120:
            clip.x0, clip.x1 = max(0, clip.x0 - 80), min(page.rect.width, clip.x1 + 80)
        if clip.height < 60:
            clip.y0, clip.y1 = max(0, clip.y0 - 40), min(page.rect.height, clip.y1 + 40)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, clip=clip)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    return img, clip


def ground_via_vlm_table(pdf_path: str, page_no: int, context_snippet: str,
                         target_entity: str, call_vlm) -> Optional[dict]:
    """表格轨视觉兜底: 200 DPI 整页 + 宏观整表检测。

    整表是页面的宏观大目标 (面积 20%-60%), VLM 大目标检测精度远高于
    小数字定位, 该路径只在矢量表格检测失败 (扫描件/无边框表) 时触发。
    """
    img, _clip = render_crop(pdf_path, page_no, around=None)  # 200 DPI 整页
    if img is None:
        return None
    extraction = {
        "field_name": "",
        "field_value": "",
        "field_unit": "",
        "context_snippet": context_snippet,
        "grounding_mode": "table",
    }
    result = call_vlm(image=img, extraction=extraction, target_entity=target_entity)
    bbox = result.get("bbox_2d")
    if not bbox or len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        return None
    m = _TABLE_NO_RE.search(context_snippet)
    return {
        "bbox_2d": [int(c) for c in bbox],
        "bbox_source": "full_table",
        "confidence": float(result.get("confidence") or 0.9),
        "found": bool(result.get("found", True)),
        "table_no": int(m.group(1)) if m else None,
    }


def ground_via_vlm_crop(pdf_path: str, page_no: int, field_value, field_unit: str,
                        context_snippet: str, target_entity: str,
                        call_vlm) -> Optional[dict]:
    """Level 2: 高清裁剪 + VLM 局部重定位。

    优先围绕上下文命中区裁剪放大 (文字像素高度 3-4 倍于 100 DPI);
    无上下文命中时降级为 200 DPI 整页。局部坐标映射回全页 0-1000。
    """
    doc = _open_pdf(pdf_path)
    if doc is None:
        return None
    page = doc[page_no - 1]
    ctx_rect = _locate_context(page, context_snippet)

    img, clip = render_crop(pdf_path, page_no, around=ctx_rect)
    if img is None:
        return None

    extraction = {
        "field_name": "",
        "field_value": field_value,
        "field_unit": field_unit,
        "context_snippet": context_snippet,
        # 候选写法提示: 数值在论文里可能以不同形式排版 (科学计数/单位换算)
        "search_hints": _value_candidates(field_value, field_unit)[:6],
    }
    result = call_vlm(image=img, extraction=extraction, target_entity=target_entity)
    bbox = result.get("bbox_2d")
    if not bbox or len(bbox) != 4:
        return None

    # 局部坐标 (0-1000, 基于裁剪图) → 全页归一化
    page_w, page_h = page.rect.width, page.rect.height
    gx0 = clip.x0 + bbox[0] / NORM * clip.width
    gy0 = clip.y0 + bbox[1] / NORM * clip.height
    gx1 = clip.x0 + bbox[2] / NORM * clip.width
    gy1 = clip.y0 + bbox[3] / NORM * clip.height
    mapped = [
        max(0, int(gx0 / page_w * NORM)),
        max(0, int(gy0 / page_h * NORM)),
        min(int(NORM), int(gx1 / page_w * NORM)),
        min(int(NORM), int(gy1 / page_h * NORM)),
    ]
    if mapped[0] >= mapped[2] or mapped[1] >= mapped[3]:
        return None
    return {
        "bbox_2d": mapped,
        "bbox_source": "vlm_crop",
        "confidence": float(result.get("confidence") or 0.9),
        "found": bool(result.get("found", True)),
        "stage1_analysis": result.get("stage1_analysis", ""),
    }


# ══════════════════════════════════════════════════════════════
# Level 3: 段落兜底 (零数据丢弃)
# ══════════════════════════════════════════════════════════════

def ground_fallback(pdf_path: str, page_no: int, context_snippet: str) -> Optional[dict]:
    """Level 3: 上下文段落级近似框 — 至少圈出原文所在位置, 保证溯源可用。"""
    doc = _open_pdf(pdf_path)
    if doc is None:
        return None
    page = doc[page_no - 1]
    ctx_rect = _locate_context(page, context_snippet)
    if ctx_rect is None:
        return None
    # 段落级外扩 (行高 × 上下各 2 行)
    line_h = max(8.0, ctx_rect.height * 1.6)
    para = fitz.Rect(
        max(0, page.rect.x0),
        max(0, ctx_rect.y0 - line_h),
        min(page.rect.width, page.rect.x1),
        min(page.rect.height, ctx_rect.y1 + line_h),
    )
    bbox = _rect_to_norm(para, page, pad=0)
    return {
        "bbox_2d": bbox,
        "bbox_source": "fallback",
        "confidence": 0.3,
        "found": True,  # 段落级定位, 记录保留但标注近似
    }


# ══════════════════════════════════════════════════════════════
# 聚合入口
# ══════════════════════════════════════════════════════════════

def hybrid_ground(pdf_path: str, page_no: int, field_value, field_unit: str,
                  context_snippet: str, target_entity: str,
                  call_vlm=None, extraction_method: str = "text") -> dict:
    """双轨分级漏斗: 正文微观定位 / 表格宏观定位。

    - extraction_method == "table": 表格轨 — 矢量整表检测 → VLM 整表宏观
      → 标题段落兜底 (整表框, bbox_source="full_table");
    - 其他 (text): 正文轨 — 矢量数值定位 → 裁剪 VLM → 段落兜底。

    Returns: {"bbox_2d": [...], "bbox_source": "vector"|"full_table"|
              "vlm_crop"|"fallback", "confidence": float, "found": bool}
    任何路径都不会返回 bbox=None — 兜底保证零数据丢弃。
    """
    # ── 表格轨: 宏定位 (整表框) ──
    # (提取链方法名两种形态: 原始 "table" / 聚合后 "vlm_table")
    if str(extraction_method or "").lower() in ("table", "vlm_table"):
        r = ground_table_vector(pdf_path, page_no, context_snippet)
        if r:
            return r
        if call_vlm is not None:
            try:
                r = ground_via_vlm_table(pdf_path, page_no, context_snippet,
                                         target_entity, call_vlm)
                if r:
                    return r
            except Exception as e:  # noqa: BLE001 — 视觉路径失败走兜底
                logger.warning("[HybridGrounder] vlm_table failed: %s", e)
        fb = ground_fallback(pdf_path, page_no, context_snippet)
        if fb:
            fb["bbox_source"] = "fallback"
            return fb
        return {
            "bbox_2d": [0, 0, int(NORM), int(NORM)],
            "bbox_source": "fallback",
            "confidence": 0.1,
            "found": False,
        }

    # ── 正文轨: 微观定位 (数值本身) ──
    # Level 1: 矢量定位 (零成本, 预期覆盖 95%+)
    r = ground_via_vector(pdf_path, page_no, field_value, field_unit, context_snippet)
    if r:
        return r

    # Level 2: 高清裁剪 + VLM (仅未命中时, 可缺省跳过)
    if call_vlm is not None:
        try:
            r = ground_via_vlm_crop(
                pdf_path, page_no, field_value, field_unit,
                context_snippet, target_entity, call_vlm,
            )
            if r:
                return r
        except Exception as e:  # noqa: BLE001 — 视觉路径失败走兜底
            logger.warning("[HybridGrounder] vlm_crop failed: %s", e)

    # Level 3: 段落兜底 (绝不返回 None)
    fb = ground_fallback(pdf_path, page_no, context_snippet)
    if fb:
        return fb
    # 无文本层且无上下文 — 全页框 (保持旧契约: 4 元组 0-1000)
    return {
        "bbox_2d": [0, 0, int(NORM), int(NORM)],
        "bbox_source": "fallback",
        "confidence": 0.1,
        "found": False,
    }
