"""Bounded PDF technical inspection and evidence page preparation."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from astroquery_ai.runtime.errors import DomainError


def probe_pdf(path: Path) -> dict:
    """Count physical pages and inspect only the three identity pages."""
    import pymupdf as fitz

    if path.stat().st_size > 100 * 1024**2:
        raise DomainError('PDF_SIZE_LIMIT', 'PDF超过单文件上限')
    with fitz.open(path) as document:
        if document.needs_pass or not document.is_pdf or len(document) == 0:
            raise DomainError('PDF_NOT_READABLE', '文件不是可读取的完整PDF')
        return {'page_count': len(document), 'metadata': document.metadata,
                'pages': [{'page': i + 1, 'text': document[i].get_text()[:64000]}
                          for i in range(min(3, len(document)))],
                'inspection_scope': 'physical_count_and_first_three_pages'}


def maximum_pages(repo, conn, tid):
    from astroquery_ai.runtime.run_policy import frozen_policy
    policy = frozen_policy(repo, conn, tid)
    return policy.get('documents', {}).get('maximum_pdf_pages') if policy else None


def inspect_pdf(path: Path) -> dict:
    import pymupdf as fitz

    if path.stat().st_size > 100 * 1024**2:
        raise DomainError("PDF_SIZE_LIMIT", "PDF超过单文件上限")
    with fitz.open(path) as document:
        if document.needs_pass or not document.is_pdf or len(document) == 0:
            raise DomainError("PDF_NOT_READABLE", "文件不是可读取的完整PDF")
        if len(document) > 1000:
            raise DomainError("PDF_PAGE_LIMIT", "PDF页数超过受控范围")
        # Page text is a navigation/identity aid, never a complete semantic scan.
        pages = []
        for index, page in enumerate(document):
            if page.rect.width <= 0 or page.rect.height <= 0:
                raise DomainError("PDF_PAGE_GEOMETRY", "PDF页尺寸无效")
            navigation_text = page.get_text()
            pages.append(
                {
                    "page": index + 1,
                    "width": page.rect.width,
                    "height": page.rect.height,
                    "text": navigation_text[:64000],
                    "text_state": "available" if navigation_text.strip() else "image_only",
                    "navigation_text_truncated": len(navigation_text) > 64000,
                    "layout_lines": [
                        {'text': ''.join(s['text'] for s in line['spans']),
                         'bbox': list(fitz.Rect(line['bbox']) * page.rotation_matrix)}
                        for block in page.get_text('dict')['blocks'] if block.get('type')==0
                        for line in block['lines']],
                    "layout_version": 'native-lines/2',
                    "layout_coordinate_space": 'rendered_page_points',
                    "layout_rotation":page.rotation,
                }
            )
        return {
            "pages": pages,
            "page_count": len(document),
            "metadata": document.metadata,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }


def identity_text(value):
    return re.sub(r'\W+','',unicodedata.normalize('NFKC',value).casefold())


def identity_page_view(inspection, *, expanded=False):
    """Actual front matter for title interpretation, never layout serialization.

    Initial scope is the first page; one expansion may inspect the other identity
    pages. Preserve physical page and exact text offsets for server validation.
    The complete inspection remains the authority for identity/version checks.
    """
    result = []
    for page in inspection['pages'][:3 if expanded else 1]:
        text = page['text']
        budget = 10000 if expanded else 8000
        end = 0
        for line in text.splitlines(keepends=True):
            if len(text[:end + len(line)].encode('utf-8')) > budget:
                break
            end += len(line)
        if not end and text:
            end = len(text.encode('utf-8')[:budget].decode('utf-8', errors='ignore'))
        result.append({'page': page['page'], 'text': text[:end],
                       'source_char_range': [0, end], 'truncated': end < len(text)})
    return result


def work_identity_facts(inspection: dict, work: dict) -> dict:
    first = "\n".join(page["text"] for page in inspection["pages"][:3])
    expected_titles = [
        title
        for record in work["records"]
        for title in record["titles"]
        if identity_text(title)
    ]
    title_hits = [title for title in expected_titles if identity_text(title) in identity_text(first)]
    identifiers = [identifier for record in work["records"] for identifier in record["dois"]]
    doi_hits = [
        identifier for identifier in identifiers if identifier.casefold() in first.casefold()
    ]
    arxiv_ids = [identifier[0] for record in work["records"] for identifier in record["arxivs"]]
    arxiv_hits = [identifier for identifier in arxiv_ids if identifier in first.casefold()]
    return {'title_hits':title_hits,'doi_hits':doi_hits,'arxiv_hits':arxiv_hits,
            'expected_titles':expected_titles,'expected_dois':identifiers,'expected_arxiv_ids':arxiv_ids}


def verify_work_identity(inspection: dict, work: dict) -> dict:
    facts=work_identity_facts(inspection,work)
    identifier_hit=bool(facts['doi_hits'] or facts['arxiv_hits'])
    short_title_only=not identifier_hit and not any(len(identity_text(t))>=24 for t in facts['title_hits'])
    if not facts['title_hits'] or facts['expected_dois'] and not identifier_hit or short_title_only:
        raise DomainError("DOCUMENT_IDENTITY_UNRESOLVED", "无法从稿件身份页核实属于目标作品",
            missing_title=not bool(facts['title_hits']),
            missing_identifier=bool(facts['expected_dois'] and not facts['doi_hits'] and not facts['arxiv_hits']))
    arxiv_ids=facts['expected_arxiv_ids']
    grade, proof = classify_version(inspection, arxiv_ids)
    return {
        "state": "verified",
        "title_hits": facts['title_hits'],
        "doi_hits": facts['doi_hits'],
        "arxiv_hits": facts['arxiv_hits'],
        "checked_pages": list(range(1, min(3, inspection["page_count"]) + 1)),
        "version_grade": grade,
        "version_evidence": proof,
    }


def classify_version(inspection, arxiv_ids):
    """Use positive manuscript evidence; a URL or ADS link label is insufficient."""
    first = inspection["pages"][0]["text"]
    # This is a deliberately narrow typeset-publication signature. Unrecognized
    # layouts remain unknown, preserving the approved last-fallback path.
    doi_line = re.search(r"(?im)^.{0,30}(?:doi\s*:|https?://doi\.org/)\s*(10\.\d{4,9}/\S+)", first)
    published = re.search(r"(?im)^.{0,180}\bpublished\s+\d{4}\s+[A-Za-z]+\s+\d{1,2}", first)
    rights = re.search(
        r"(?im)^.{0,30}[©c](?:\u20dd)?\s*\d{4}\s*\.?.{0,100}(?:American Astronomical Society|AAS|EDP Sciences|Royal Astronomical Society)",
        first,
    )
    if doi_line and published and rights:
        return "published", {
            "rule_id": "typeset-doi-publication-rights-1",
            "page": 1,
            "fragments": [doi_line.group(0), published.group(0), rights.group(0)],
        }
    accepted = re.search(r"(?im)^\s*(?:author[’']?s?\s+)?accepted\s+manuscript\b.{0,180}", first)
    if accepted:
        return "accepted", {
            "rule_id": "explicit-accepted-manuscript-1",
            "page": 1,
            "fragments": [accepted.group(0)],
        }
    for identifier in arxiv_ids:
        match = re.search(r"(?i)arxiv\s*:\s*" + re.escape(identifier) + r"(?:v\d+)?\b", first)
        if match:
            return "preprint", {
                "rule_id": "matching-arxiv-manuscript-label-1",
                "page": 1,
                "fragments": [match.group(0)],
            }
    return "unknown", {
        "rule_id": "version-level-unconfirmed-1",
        "page": 1,
        "fragments": [],
        "limitation": "verified_complete_work_last_fallback_only",
    }


def page_image(path: Path, page_number: int, *, dpi=150, display_only=False) -> bytes:
    import pymupdf as fitz

    with fitz.open(path) as document:
        if not 1 <= page_number <= len(document):
            raise DomainError("PAGE_OUT_OF_RANGE", "页码不属于此PDF", 422)
        page = document[page_number - 1]
        size = page.rect * (dpi / 72)
        if size.width * size.height > 16_000_000 or max(size.width, size.height) > 2048:
            if display_only:
                scale = min(dpi / 72, 2048 / max(page.rect.width, page.rect.height))
                return page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")
            raise DomainError("PAGE_REQUIRES_TILING", "此页需分区读取，不能降低清晰度冒充已读")
        return page.get_pixmap(dpi=dpi, alpha=False).tobytes("png")
