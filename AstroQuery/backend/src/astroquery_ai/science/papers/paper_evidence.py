"""Physical-page navigation, local text blocks and evidence windows."""
from __future__ import annotations
from astroquery_ai.science.measurements.admission_contracts import normalized
import re
import unicodedata
from astroquery_ai.science.catalogs import identifier_typography


def merge_locator_check(check, locator):
    if check is None:
        return None
    return check.model_copy(
        update={
            key: getattr(locator, key)
            for key in ("subject", "printed_subject", "subject_evidence", "subject_link")
        }
    )


def page_blocks(pages):
    blocks = []
    for page, text in pages.items():
        lines = text.splitlines(keepends=True)
        start, pending = (0, "")
        for end, line in enumerate(lines, 1):
            pending += line
            if len(pending) >= 650 or end == len(lines):
                blocks.append(
                    {"page": page, "block_id": f"p{page}:l{start + 1}-{end}", "text": pending}
                )
                start, pending = (end, "")
    return blocks


def resolve_context_locator(index, locator, core_pages):
    """Resolve source headings/captions before ambiguous mentions of them."""
    label = re.match("\\s*(Table|Fig(?:ure)?\\.?|Section|§)\\s*(\\d+(?:\\.\\d+)*)", locator, re.I)
    eligible = [p for p in index["pages"] if p["page"] not in core_pages]
    if label:
        kind, number = label.groups()
        number = re.escape(number)
        if kind.casefold() in {"section", "§"}:
            pattern = f"^[ \\t]*(?:§[ \\t]*)?{number}\\.?[ \\t]+[A-Za-z][^\\n]{{2,}}$"
        else:
            prefix = "Table" if kind.casefold() == "table" else "Fig(?:ure)?\\.?"
            pattern = f"^\\s*{prefix}\\s*{number}(?:\\s*[.:]\\s*[^\\n]*|\\s*)$"
        matches = [p["page"] for p in eligible if re.search(pattern, p["text"], re.I | re.M)]
        if matches:
            return matches
    return [p["page"] for p in eligible if normalized(locator) in normalized(p["text"])]


def context_fragments(index, target, core_pages, context_pages):
    """Carry literal identity/preceding context, at most two non-core pages.

    Navigation only: a target name elsewhere never establishes a candidate's
    local subject. The model must still cite the local relationship/role.
    """
    native = {item["page"]: item["text"] for item in index["pages"]}
    available = set(core_pages) | set(context_pages)
    slots = max(0, 2 - len(set(context_pages) - set(core_pages)))
    names = [target["main_id"], *target.get("aliases", [])]
    names.extend((name[4:] for name in list(names) if name.startswith("PSR ")))
    names = {normalized(identifier_typography(name)) for name in names if name}
    first = min(core_pages)
    candidates = [
        block
        for block in page_blocks(native)
        if block["page"] not in available
        and any((name in normalized(identifier_typography(block["text"])) for name in names))
    ]
    candidates.sort(
        key=lambda block: (abs(block["page"] - first), block["page"] > first, block["block_id"])
    )
    selected, selected_pages = ([], set())
    headings = [
        block
        for block in page_blocks(native)
        if block["page"] < first
        and block["page"] not in available
        and re.search("^[ \\t]*\\d+(?:\\.\\d+)*\\.?[ \\t]+[A-Z][^\\n]{3,}$", block["text"], re.M)
    ]
    headings.sort(key=lambda block: (block["page"], block["block_id"]), reverse=True)
    if slots and headings:
        selected.append(headings[0])
        selected_pages.add(headings[0]["page"])
    elif slots and candidates:
        selected.append(candidates[0])
        selected_pages.add(candidates[0]["page"])
    previous = first - 1
    if (
        previous in native
        and previous not in available
        and (previous in selected_pages or len(selected_pages) < slots)
    ):
        previous_blocks = page_blocks({previous: native[previous]})
        selected.extend(previous_blocks[-2:])
        selected_pages.add(previous)
    if len(selected_pages) < slots:
        identity = next(
            (block for block in candidates if block["page"] not in selected_pages), None
        )
        if identity:
            selected.append(identity)
            selected_pages.add(identity["page"])
    selected = list({block["block_id"]: block for block in selected}.values())
    return (selected, {page: native[page] for page in selected_pages})


def document_frame(index, core_pages):
    """Carry actual front matter as competing scope evidence, never as an answer.

    This is a small native-text document frame, not another PDF/image reading
    batch. Local sections still take precedence over a paper's general subject.
    """
    first = next((p for p in index["pages"] if p["page"] == 1), None)
    if first is None or 1 in core_pages:
        return []
    return page_blocks({1: first["text"]})[:4]


def fit_native_blocks(instruction, field, content_tail, blocks, *, maximum=48000):
    """Fit complete native blocks across pages, without clipping any block."""
    from astroquery_ai.runtime.calls import input_upper_bound
    from astroquery_ai.runtime.codec import canonical

    trial = {**instruction, field: blocks}
    content = [{"type": "text", "text": canonical(trial).decode()}, *content_tail]
    if input_upper_bound([{"role": "user", "content": content}]) <= maximum:
        return (trial, content, blocks)
    trial[field] = []
    trial["native_core_transcript_state"] = "partial_blocks_full_images_retained"
    trial["native_transcript_instruction"] = (
        "原文块是部分辅助转写，核心页图像均完整提供。只能使用实际列出的block_id；图像中没有对应块的文字用page和逐字quote且block_ids=[]，不能编造ID。上下文块不获得提取权限。"
    )
    base_content = [{"type": "text", "text": canonical(trial).decode()}, *content_tail]
    fixed = input_upper_bound([{"role": "user", "content": base_content}])
    by_page = {}
    for block in blocks:
        by_page.setdefault(block["page"], []).append(block)
    selected = []
    for i in range(max((len(group) for group in by_page.values()), default=0)):
        for group in by_page.values():
            if i < len(group) and fixed + len(canonical([*selected, group[i]])) - 2 <= maximum:
                selected.append(group[i])
    trial[field] = selected
    return (trial, [{"type": "text", "text": canonical(trial).decode()}, *content_tail], selected)


def target_quantity_pages(spec, index, core_pages):
    """Bounded completeness cue, never scientific permission to admit a value."""
    names = [spec["target"]["main_id"], *spec["target"].get("aliases", [])]
    labels = [
        label
        for binding in spec["properties"]
        for label in [
            binding["definition"]["name_en"],
            binding["definition"]["name_cn"],
            *binding["definition"].get("aliases", []),
        ]
    ]
    selected = []
    for page in index["pages"]:
        if page["page"] not in core_pages:
            continue
        text = unicodedata.normalize("NFKC", page["text"])
        lexical = normalized(identifier_typography(text))
        target_seen = any((normalized(identifier_typography(name)) in lexical for name in names))
        for name in names:
            if name.startswith("PSR "):
                target_seen |= normalized(identifier_typography(name[4:])) in lexical
                match = re.fullmatch("PSR ([BJ])(\\d{4}[+-]\\d{2,4})", name)
                if match and re.search(f"PSR\\s*{match[1]}\\b", text, re.I):
                    target_seen |= normalized(match[2]) in lexical
        property_seen = any(
            (
                re.search("(?<!\\w)" + re.escape(label) + "(?!\\w)", text, re.I)
                for label in labels
                if label
            )
        )
        if target_seen and property_seen:
            selected.append(page["page"])
    return selected


def complete_native_evidence(pages, blocks, required_pages):
    actual = {b["block_id"]: b for b in blocks}
    return all(
        (
            page in pages
            and bool(pages[page].strip())
            and all(
                (
                    expected["block_id"] in actual
                    and actual[expected["block_id"]]["page"] == page
                    and (actual[expected["block_id"]]["text"] == expected["text"])
                    for expected in page_blocks({page: pages[page]})
                )
            )
            for page in required_pages
        )
    )
