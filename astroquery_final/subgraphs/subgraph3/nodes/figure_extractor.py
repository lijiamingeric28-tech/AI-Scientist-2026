"""Figure 证据提取节点（独立于数据提取通路）

职责：对每篇论文的每一页，用 VLM 检测页面中的图表区域（bbox），
判断每张图与用户查询的相关性；相关的图按 bbox 裁剪保存到
output/figures/<query_id>/，供前端直接展示原始论文证据。

设计：
- 页级并发（复用 bbox_annotator 的超高并发模式，max_workers=100）
- 一次 VLM 调用同时完成"图检测 + 相关性筛选"
- 只保存 is_relevant=true 的裁剪图
- 产出 figure_evidence 列表，进入 final_output（不进质量管线）
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from PIL import Image

from astroquery_ai.config import PROJECT_ROOT

from ..config.settings import settings
from ..schemas.state import ExtractionState
from ..utils.figure_client import call_qwen_figure_detect
from ..utils.image_cache import image_cache
from ..utils.logger import get_logger

logger = get_logger(__name__)

# 输出根目录（前端静态服务 output/ 即可访问图片）
OUTPUT_ROOT = PROJECT_ROOT / "output"


def _safe_name(s: str) -> str:
    """文件名安全化（替换 / : 空格）"""
    return s.replace("/", "_").replace(":", "_").replace(" ", "_")


def _crop_figure(
    image: Image.Image,
    bbox: List[float],
    out_path: Path,
) -> bool:
    """按 1000 归一化 bbox 裁剪页面图并保存。

    Returns:
        是否成功保存
    """
    try:
        if len(bbox) != 4:
            return False
        w, h = image.size
        x0 = int(max(0, min(bbox[0], 1000)) / 1000 * w)
        y0 = int(max(0, min(bbox[1], 1000)) / 1000 * h)
        x1 = int(max(0, min(bbox[2], 1000)) / 1000 * w)
        y1 = int(max(0, min(bbox[3], 1000)) / 1000 * h)
        if x1 <= x0 or y1 <= y0:
            return False
        cropped = image.crop((x0, y0, x1, y1))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(out_path, format="PNG")
        return True
    except Exception as e:
        logger.warning(f"[FigureExtractor] 裁剪保存失败 {out_path.name}: {e}")
        return False


def _is_relevant(fig: Dict) -> bool:
    """判断 VLM 标记的相关性（兼容 bool / 字符串 "true"/"false"）"""
    v = fig.get("is_relevant")
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1")
    return False


def _process_page(
    bibcode: str,
    page: int,
    image_path: str,
    target_entity: str,
    property_spec: List[Dict],
    query_id: str,
) -> List[Dict]:
    """处理单页：VLM 检测 + 筛选 + 裁剪保存，返回该页的 figure_evidence 条目"""
    try:
        image = image_cache.load_images([image_path])
        if not image:
            logger.warning(f"[FigureExtractor] 页面图片加载失败 {bibcode} p{page}")
            return []
        page_image = image[0]
    except Exception as e:
        logger.warning(f"[FigureExtractor] 页面图片加载异常 {bibcode} p{page}: {e}")
        return []

    result = call_qwen_figure_detect(
        image=page_image,
        page=page,
        target_entity=target_entity,
        property_spec=property_spec,
    )
    if not result:
        return []

    evidence = []
    figures = result.get("figures", []) or []
    for idx, fig in enumerate(figures, 1):
        if not _is_relevant(fig):
            continue

        filename = f"{_safe_name(bibcode)}_p{page}_f{idx}.png"
        rel_dir = f"figures/{query_id}"
        out_path = OUTPUT_ROOT / rel_dir / filename

        if not _crop_figure(page_image, fig.get("bbox", []), out_path):
            continue

        evidence.append({
            "source_id": bibcode,
            "page": page,
            "figure_index": idx,
            "caption": fig.get("caption", ""),
            "description": fig.get("description", ""),
            "relevance": fig.get("relevance", "medium"),
            "relevance_reason": fig.get("relevance_reason", ""),
            "image_path": f"{rel_dir}/{filename}",
        })

    if evidence:
        logger.info(f"[FigureExtractor] {bibcode} p{page}: {len(evidence)} 张相关图")
    return evidence


def figure_extractor(state: ExtractionState) -> ExtractionState:
    """
    Figure 证据提取节点（页级并发）。

    输入：paper_image_paths（pdf_batch_converter 产物）
    输出：figure_evidence（相关图列表，含裁剪保存路径）
    """
    paper_image_paths = state.get("paper_image_paths", {}) or {}
    target_entity = state.get("target_entity", "")
    # 相关性锚点 = P1 标准化的 PropertySpec（与数据提取链路同源）
    property_spec = state.get("property_spec", []) or []
    query_id = state.get("query_id", "")

    # 构建页级任务列表
    tasks = []
    for bibcode, image_paths in paper_image_paths.items():
        for page, image_path in enumerate(image_paths, 1):
            tasks.append({
                "bibcode": bibcode,
                "page": page,
                "image_path": image_path,
            })

    if not tasks:
        logger.info("[FigureExtractor] 无页面可检测")
        # 只返回本节点更新的字段（与 vlm_batch_extractor 并行，返回全量 state 会冲突）
        return {"figure_evidence": []}

    logger.info(f"[FigureExtractor] 检测 {len(tasks)} 页 ({len(paper_image_paths)} 篇论文)")

    # 页级并发（复用 bbox 的超高并发配置）
    max_workers = getattr(settings, "bbox_concurrency", type(
        "obj", (object,), {"max_workers": 100, "max_retries": 3}
    )()).max_workers

    all_evidence: List[Dict] = []
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _process_page,
                t["bibcode"], t["page"], t["image_path"],
                target_entity, property_spec, query_id,
            ): t
            for t in tasks
        }
        for future in as_completed(futures):
            task = futures[future]
            completed += 1
            try:
                ev = future.result()
                all_evidence.extend(ev)
            except Exception as e:
                logger.warning(
                    f"[FigureExtractor] 页面处理失败 {task['bibcode']} p{task['page']}: {e}"
                )
            if completed % 50 == 0:
                logger.info(f"[FigureExtractor] 进度 {completed}/{len(tasks)}")

    logger.info(
        f"[FigureExtractor] 完成: {len(all_evidence)} 张相关图 "
        f"(检测 {len(tasks)} 页, {completed} 成功)"
    )
    # 只返回本节点更新的字段（并行节点返回全量 state 会导致 key 冲突）
    return {"figure_evidence": all_evidence}
