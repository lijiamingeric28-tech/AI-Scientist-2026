"""PDF 下载节点"""

import os
import logging
import time
import threading
import requests
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional

from ..state import RetrievalState
from ..config import config

logger = logging.getLogger(__name__)


def _remove_part_file(save_path: str) -> None:
    """清理下载中断/失败残留的 .part 临时文件（M-25）"""
    part_path = save_path + ".part"
    try:
        if os.path.exists(part_path):
            os.remove(part_path)
    except OSError:
        pass


def download_from_url(
    url: str,
    save_path: str,
    timeout: int = 60,
    max_size_mb: int = 50,
    headers: Optional[Dict] = None,
) -> dict:
    """
    从 URL 下载 PDF 文件

    Args:
        url: PDF URL
        save_path: 保存路径
        timeout: 超时时间（秒）
        max_size_mb: 最大文件大小（MB）
        headers: 附加请求头（如 ADS API 的 Authorization），合并进默认 UA

    Returns:
        {"success": bool, "file_size": int, "error": str}
    """
    try:
        merged_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        if headers:
            merged_headers.update(headers)

        response = requests.get(url, headers=merged_headers, timeout=timeout, stream=True)

        if response.status_code != 200:
            return {
                "success": False,
                "file_size": 0,
                "error": f"HTTP {response.status_code}"
            }

        # 检查文件大小
        content_length = response.headers.get('content-length')
        if content_length:
            size_mb = int(content_length) / (1024 * 1024)
            if size_mb > max_size_mb:
                return {
                    "success": False,
                    "file_size": int(content_length),
                    "error": f"File too large: {size_mb:.1f}MB > {max_size_mb}MB"
                }

        # 写临时文件，校验通过后再改名为正式路径。
        # 避免瀑布流中前一个 URL 失败残留的部分字节被下一个 URL 续写。
        part_path = save_path + ".part"
        if os.path.exists(part_path):
            os.remove(part_path)

        # M-25: 流式字节限流——Content-Length 缺失/失真（chunked 编码）时在
        # 写循环内累计已写字节，超 max_size_mb 即中断、删 .part 返回失败，
        # 避免无界写盘直至超时
        max_bytes = max_size_mb * 1024 * 1024
        written = 0
        too_large = False
        with open(part_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                written += len(chunk)
                if written > max_bytes:
                    too_large = True
                    break
                f.write(chunk)

        if too_large:
            os.remove(part_path)
            return {
                "success": False,
                "file_size": written,
                "error": f"File too large: {written / (1024 * 1024):.1f}MB > {max_size_mb}MB"
            }

        file_size = os.path.getsize(part_path)

        # 验证文件是否为 PDF
        with open(part_path, 'rb') as f:
            header = f.read(4)
            if header != b'%PDF':
                os.remove(part_path)
                return {
                    "success": False,
                    "file_size": file_size,
                    "error": "Not a valid PDF file"
                }

        os.replace(part_path, save_path)

        return {
            "success": True,
            "file_size": file_size,
            "error": None
        }

    except requests.Timeout:
        # M-25: 失败路径同样清理 .part 残留，避免瀑布流续写脏文件
        _remove_part_file(save_path)
        return {"success": False, "file_size": 0, "error": "Timeout"}
    except Exception as e:
        _remove_part_file(save_path)
        return {"success": False, "file_size": 0, "error": str(e)}


def build_ordered_urls(paper: dict, unpaywall_urls: List[Dict]) -> List[Dict]:
    """
    构建瀑布式下载的 URL 列表（按优先级排序）

    优先级：
    1. arXiv 直链（实测 100% 成功、无反爬、无需前置查询）
    2. Unpaywall best_pdf
    3. Unpaywall alternates
    4. ADS esources 的 PUB_PDF（开放期刊兜底）

    Args:
        paper: 论文元数据（含 arxiv_id, esources）
        unpaywall_urls: Unpaywall 返回的 URL 列表

    Returns:
        按优先级排序的 URL 列表
    """
    ordered = []

    # 1. arXiv 直链（最高优先级，实测 100% 成功）
    arxiv_id = paper.get("arxiv_id")
    if arxiv_id:
        ordered.append({
            "url": f"https://arxiv.org/pdf/{arxiv_id}",
            "source": "arxiv_direct"
        })

    # 2 & 3. Unpaywall（保持原有顺序：best 在前，alternates 在后）
    ordered.extend(unpaywall_urls or [])

    # 4. ADS PUB_PDF 兜底（开放期刊的出版社全文）
    esources = paper.get("esources") or []
    if "PUB_PDF" in esources:
        bibcode = paper.get("bibcode", "")
        doi = paper.get("doi")
        if doi:
            entry = {
                "url": f"https://api.adsabs.harvard.edu/v1/link_gateway/{bibcode}/PUB_PDF",
                "source": "ads_pub_pdf"
            }
            # R2-1: link_gateway 需要 Authorization 头，否则必 401。
            # token 来自统一 Settings（config.api['ads']['token']）；无 token 时
            # 保持原行为（不带头），仅告警提示。
            token = config.api['ads']['token']
            if token:
                entry["headers"] = {"Authorization": f"Bearer {token}"}
            else:
                logger.warning(
                    "[Waterfall] ADS token 未配置，PUB_PDF 兜底请求可能 401: "
                    f"{paper.get('bibcode')}"
                )
            ordered.append(entry)

    return ordered


def download_with_waterfall_strategy(
    paper: dict,
    urls: List[Dict],
    save_dir: str,
    timeout: int = 60,
    max_size_mb: int = 50
) -> dict:
    """
    瀑布式下载策略（依次尝试所有 URL）

    Args:
        paper: 论文元数据（含 arxiv_id, esources）
        urls: Unpaywall 返回的所有 URL
        save_dir: 保存目录
        timeout: 超时时间（秒）
        max_size_mb: 最大文件大小（MB）

    Returns:
        {"success": True/False, "local_path": "...", "source": "...", "file_size": ..., "error": None}
    """
    # 生成保存路径（绝对路径 + 平台原生分隔符，供下游 Node 3 直接打开）
    safe_id = paper["bibcode"].replace("/", "_").replace(":", "_")
    save_path = str((Path(save_dir) / f"{safe_id}.pdf").resolve())

    # 构建按优先级排序的 URL 列表（arXiv 最前）
    ordered_urls = build_ordered_urls(paper, urls)

    if not ordered_urls:
        logger.debug(f"[Waterfall] No URLs available for {paper['bibcode']}")
        return {
            "success": False,
            "local_path": None,
            "source": None,
            "file_size": None,
            "error": "no_url_available"
        }

    logger.debug(f"[Waterfall] Starting download for {paper['bibcode']}")
    logger.debug(f"[Waterfall] Total sources to try: {len(ordered_urls)}")

    for idx, url_info in enumerate(ordered_urls, 1):
        url = url_info["url"]
        source_name = url_info["source"]

        logger.debug(f"[Waterfall] [{idx}/{len(ordered_urls)}] Trying {source_name}: {url[:80]}...")

        try:
            result = download_from_url(
                url, save_path, timeout, max_size_mb,
                headers=url_info.get("headers")
            )

            if result["success"]:
                logger.debug(f"[Waterfall] SUCCESS from {source_name}")
                return {
                    "success": True,
                    "local_path": save_path,
                    "source": source_name,
                    "file_size": result["file_size"],
                    "error": None
                }
            else:
                logger.debug(f"[Waterfall] Failed from {source_name}: {result.get('error')}")

        except Exception as e:
            logger.debug(f"[Waterfall] Exception from {source_name}: {e}")

    # 所有源都失败
    logger.warning(f"[Waterfall] All {len(ordered_urls)} sources failed for {paper['bibcode']}")
    return {
        "success": False,
        "local_path": None,
        "source": None,
        "file_size": None,
        "error": f"All sources failed ({len(ordered_urls)} tried)"
    }


def pdf_download(state: RetrievalState) -> RetrievalState:
    """
    PDF 瀑布式下载节点

    步骤：
    1. 准备下载列表
    2. 并发下载（max_workers=5）
    3. 展示进度
    4. 构建 paper_sources（仅成功下载的）
    5. 记录失败信息

    Args:
        state: 当前状态

    Returns:
        更新后的状态
    """
    papers_metadata = state.get("ads_papers_metadata", [])
    unpaywall_results = state.get("unpaywall_results", {})
    query_id = state["query_id"]

    if not papers_metadata:
        logger.info("[PDF Download] No papers to download, skipping")
        state["pdf_download_status"] = "skipped"
        state["download_paths"] = []
        state["failed_downloads"] = []
        state["paper_sources"] = []
        # 只返回更新的字段
        return {
            "pdf_download_status": state.get("pdf_download_status"),
            "pdf_download_progress": state.get("pdf_download_progress", {}),
            "download_paths": state.get("download_paths", []),
            "failed_downloads": state.get("failed_downloads", []),
            "paper_sources": state.get("paper_sources", [])
        }

    logger.info(f"[PDF Download] Query ID: {query_id}")
    logger.info(f"[PDF Download] Papers: {len(papers_metadata)}")

    state["pdf_download_status"] = "running"

    # Step 1: 准备下载目录（papers_dir 已在 config 中解析为绝对路径）
    save_dir = str((Path(config.output['papers_dir']) / query_id).resolve())
    os.makedirs(save_dir, exist_ok=True)
    logger.info(f"[PDF Download] Save directory: {save_dir}")

    # Step 2: 准备下载列表
    # 不再因缺 DOI 跳过：无 DOI 的论文可能仍有 arXiv ID（P0 修复），
    # 全部进队列，由瀑布策略内部决定能否拿到 URL。
    download_tasks = []
    for paper in papers_metadata:
        bibcode = paper.get("bibcode")
        if not bibcode:
            continue

        doi = paper.get("doi")
        urls = unpaywall_results.get(doi, []) if doi else []

        download_tasks.append({
            "paper": paper,
            "urls": urls,
            "save_dir": save_dir
        })

    logger.info(f"[PDF Download] Papers in queue: {len(download_tasks)}")

    # Step 3: 并发下载
    downloaded_papers = []
    failed_downloads = []

    total = len(download_tasks)
    completed = 0

    pdf_config = config.retrieval['papers']['pdf_download']

    # R2-3: 仅 arXiv 直链任务受 arxiv_max_workers 并发限制（礼貌性限流），
    # 非 arXiv 任务使用 max_workers 全并发 —— 不再全局压到 min(max_workers, arxiv_max_workers)。
    max_workers = pdf_config['max_workers']
    arxiv_semaphore = threading.Semaphore(pdf_config.get('arxiv_max_workers', 3))

    def download_single(task):
        paper = task["paper"]
        urls = task["urls"]
        save_dir = task["save_dir"]

        # arXiv 有礼貌性频率限制：并发上限 arxiv_max_workers + 每次请求间隔 arxiv_delay 秒
        if paper.get("arxiv_id"):
            with arxiv_semaphore:
                time.sleep(pdf_config.get('arxiv_delay', 1.0))
                return download_with_waterfall_strategy(
                    paper, urls, save_dir,
                    timeout=pdf_config['timeout'],
                    max_size_mb=pdf_config['max_file_size_mb']
                )

        # 使用瀑布式下载
        return download_with_waterfall_strategy(
            paper, urls, save_dir,
            timeout=pdf_config['timeout'],
            max_size_mb=pdf_config['max_file_size_mb']
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download_single, task): task for task in download_tasks}

        for future in as_completed(futures):
            task = futures[future]
            paper = task["paper"]

            try:
                result = future.result()

                completed += 1

                # 更新进度
                state["pdf_download_progress"] = {
                    "completed": completed,
                    "total": total,
                    "current_paper": paper.get("bibcode", "unknown")
                }

                if result["success"]:
                    downloaded_papers.append({
                        "bibcode": paper["bibcode"],
                        "doi": paper.get("doi"),
                        "local_path": result["local_path"],
                        "file_size_mb": round(result["file_size"] / (1024 * 1024), 2),
                        "download_source": result["source"],
                        "downloaded_at": datetime.now().isoformat(),
                        # 论文级性质子集（ADS 命中标记透传，VLM 单一性质提取依据；
                        # 空列表 → 提取端全量 spec 兜底）
                        "property_ids": paper.get("property_ids", []),
                    })
                    logger.info(f"[PDF Download] [{completed}/{total}] [OK] {paper['bibcode']}")
                else:
                    failed_downloads.append({
                        "bibcode": paper["bibcode"],
                        "doi": paper.get("doi"),
                        "title": paper.get("title"),
                        "reason": result.get("error", "Unknown error")
                    })
                    logger.warning(f"[PDF Download] [{completed}/{total}] [FAIL] {paper['bibcode']}: {result.get('error')}")

            except Exception as e:
                completed += 1
                failed_downloads.append({
                    "bibcode": paper["bibcode"],
                    "doi": paper.get("doi"),
                    "title": paper.get("title"),
                    "reason": str(e)
                })
                logger.error(f"[PDF Download] [{completed}/{total}] [FAIL] {paper['bibcode']}: {e}")

    # Step 4: 构建 paper_sources（仅包含成功下载的）
    paper_sources = []
    downloaded_bibcodes = {p["bibcode"] for p in downloaded_papers}

    for paper in papers_metadata:
        if paper["bibcode"] in downloaded_bibcodes:
            # 找到对应的下载信息
            download_info = next(p for p in downloaded_papers if p["bibcode"] == paper["bibcode"])

            source = {
                "source_id": paper["bibcode"],  # 使用 bibcode 作为 source_id
                "source_type": "paper",
                "doi": paper.get("doi"),
                "title": paper["title"],
                "authors": paper["authors"],
                "year": paper["year"],
                "journal": paper["journal"],
                "access_path": download_info["local_path"],
                "retrieval_priority": paper["retrieval_priority"],
                "abstract": paper.get("abstract"),
                "keywords": paper.get("keywords", []),
                "search_query": paper["search_query"],
                "search_rank": paper["search_rank"],
                # 论文级性质子集（supplementary 按 parent 论文性质做列映射）
                "property_ids": paper.get("property_ids", []),
            }
            paper_sources.append(source)

    # Step 5: 更新状态
    state["pdf_download_status"] = "completed"
    state["download_paths"] = downloaded_papers
    state["failed_downloads"] = failed_downloads
    state["paper_sources"] = paper_sources

    state["pdf_download_progress"] = {
        "completed": total,
        "total": total,
        "current_paper": "Completed"
    }

    # 按来源统计（验证 P0 提升效果用）
    from collections import Counter
    source_stats = Counter(p["download_source"] for p in downloaded_papers)
    n_arxiv_papers = sum(1 for p in papers_metadata if p.get("arxiv_id"))
    n_no_url = sum(1 for f in failed_downloads if f.get("reason") == "no_url_available")

    logger.info("[PDF Download] Completed!")
    logger.info(f"[PDF Download]   Success: {len(downloaded_papers)}")
    logger.info(f"[PDF Download]   Failed: {len(failed_downloads)}")
    logger.info(f"[PDF Download]   有 arXiv ID 的论文: {n_arxiv_papers}/{len(papers_metadata)}")
    logger.info(f"[PDF Download]   成功来源分布: {dict(source_stats) or '无'}")
    logger.info(f"[PDF Download]   无任何 URL 可用: {n_no_url}")

    # 只返回更新的字段
    return {
        "pdf_download_status": state.get("pdf_download_status"),
        "pdf_download_progress": state.get("pdf_download_progress", {}),
        "download_paths": state.get("download_paths", []),
        "failed_downloads": state.get("failed_downloads", []),
        "paper_sources": state.get("paper_sources", [])
    }
