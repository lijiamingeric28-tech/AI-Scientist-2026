"""Keep reported coordinates, literal values and distinct uncertainty components."""
from __future__ import annotations
from astroquery_ai.science.measurements.admission_contracts import normalized
from decimal import Decimal, InvalidOperation
import re
import unicodedata


def native_numeric_conflict(proposal):
    """Identify a model-computed point value, never infer its physical meaning."""
    if (
        proposal.value.kind != "real"
        or proposal.limit != "none"
    ):
        return None
    raw = unicodedata.normalize("NFKC", proposal.raw_value).replace("−", "-").strip()
    number = "[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?"
    match = re.fullmatch("(" + number + ")(?:\\(\\d+\\))?(?:\\s+(?:[A-Za-zµμ%].*|±.*))?", raw)
    if not match:
        return None
    try:
        literal, interpreted = (Decimal(match[1]), Decimal(str(proposal.value.value)))
        if literal.is_finite() and interpreted.is_finite() and (literal != interpreted):
            return {
                "source_numeric_literal": match[1],
                "model_value": str(proposal.value.value),
                "model_unit": proposal.unit,
                "reason": "native_numeric_coordinate_changed",
            }
    except InvalidOperation:
        pass
    return None


def preserve_literal_native_coordinate(proposal, pages):
    """Copy a complete, explicit number+unit actually printed in owned text.

    This is source transcription, not a target conversion or quantity verdict.
    Nonlinear/compound/limit forms still require the existing interpretation.
    """
    if (
        proposal.value.kind != "real"
        or proposal.limit != "none"
        or (proposal.page not in pages)
    ):
        return (proposal, None)

    def normalize(s):
        return unicodedata.normalize("NFKC", s).replace("−", "-")

    raw = normalize(proposal.raw_value).strip()
    match = re.fullmatch(
        "([+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?)\\s*([A-Za-zµμ%].*)", raw
    )
    if not match:
        return (proposal, None)
    number, unit = match.groups()
    unit = unit.strip()
    literal = re.escape(number) + "\\s*" + re.escape(unit).replace("\\ ", "\\s*")
    if not re.search("(?<![\\d.])" + literal + "(?!\\w)", normalize(pages[proposal.page])):
        return (proposal, None)
    from astroquery_ai.science.units import parse_unit

    try:
        native = parse_unit(unit)
    except (ValueError, TypeError):
        return (proposal, None)
    try:
        same = (
            Decimal(str(proposal.value.value)) == Decimal(number)
            and parse_unit(proposal.unit) == native
        )
    except (ValueError, TypeError, InvalidOperation):
        same = False
    if same and not (str(native.physical_type) != 'unknown' and proposal.representation != 'linear'):
        return (proposal, None)
    proof = {
        "schema_version": "PaperNativeLiteralPreservation/1",
        "page": proposal.page,
        "literal": proposal.raw_value,
        "source_number": number,
        "source_unit": unit,
        "previous_model_value": proposal.value.model_dump(mode="json"),
        "previous_model_unit": proposal.unit,
        "previous_model_representation": proposal.representation,
        "previous_model_errors": [e.model_dump(mode='json') for e in proposal.errors],
        "method": "complete_literal_in_owned_native_page",
        "target_value_computed": False,
        "uncertainty_raw_preserved_for_separate_check": bool(proposal.errors),
    }
    errors = [
        e.model_copy(
            update={
                "interpretation_state": "unresolved",
                "values": None,
                "source_unit": None,
                "reason": "native_main_coordinate_restored_error_requires_separate_source_check",
            }
        )
        for e in proposal.errors
    ]
    physical = str(native.physical_type) != 'unknown'
    return (
        proposal.model_copy(
            update={
                "value": proposal.value.model_copy(update={"value": number}),
                "unit": unit,
                "errors": errors,
                **({'representation':'linear', 'representation_parameters':None} if physical else {}),
            }
        ),
        proof,
    )


def preserve_parenthetical_errors(proposal):
    """Check a proposed last-digit interpretation, without calculating a new result.

    Retain an inconsistent raw error unresolved; do not replace the model's
    proposal with a silent correction, infer a sigma level or drop the main value.
    """
    match = re.fullmatch(
        "\\s*([+-]?\\d+(?:\\.\\d+)?)\\((\\d+)\\)([eE][+-]?\\d+)?\\s*", proposal.raw_value
    )
    if not match or proposal.value.kind not in {"real", "integer"}:
        return proposal
    literal = match[1] + (match[3] or "")
    expected = Decimal(match[2]).scaleb(Decimal(literal).as_tuple().exponent)
    errors = []
    for error in proposal.errors:
        if (
            error.kind == "symmetric_delta"
            and error.interpretation_state == "parsed"
            and (f"({match[2]})" in error.raw_text.replace(" ", ""))
        ):
            try:
                consistent = Decimal(error.values["delta"]) == expected
            except (KeyError, TypeError, InvalidOperation):
                consistent = False
            if not consistent:
                error = error.model_copy(
                    update={
                        "interpretation_state": "unresolved",
                        "values": None,
                        "reason": "parenthetical_last_digits_inconsistent_with_reported_precision",
                    }
                )
        errors.append(error)
    return proposal.model_copy(update={"errors": errors})


def positive_semantic_label(pattern, text, *, check_after=True):
    """A negated/unstated label cannot establish a positive uncertainty claim.

    This is a conservative source guard, not a natural-language truth oracle.
    Losing an unsupported label leaves the numerical error available.
    """
    for match in re.finditer(pattern, text, re.I):
        before = re.split("[\\n,;.!?。；，]", text[: match.start()])[-1][-100:]
        after = re.split("[\\n,;.!?。；，]", text[match.end() :])[0][:100]
        negated_before = re.search(
            "\\b(?:not|no|without|unspecified|unknown)\\b[^,;.!?]{0,70}$|(?:不是|并非|未给出|未声明|无)[^，；。]{0,35}$",
            before,
            re.I,
        )
        unstated_after = check_after and re.search(
            "\\b(?:not\\s+(?:stated|specified|defined|reported)|unspecified|unknown|unreported)\\b|未(?:给出|声明|说明|报告)|未知",
            after,
            re.I,
        )
        if not negated_before and (not unstated_after):
            return True
    return False


def preserve_uncertainty_semantics(proposal, pages, visible_blocks):
    """Unproved error labels remain unknown; numeric components remain intact."""
    blocks = {b["block_id"]: b for b in visible_blocks}
    checked = []
    for error in proposal.errors:
        texts = []
        for anchor in error.semantics_evidence:
            if anchor.block_ids and all(
                (key in blocks and blocks[key]["page"] == anchor.page for key in anchor.block_ids)
            ):
                texts.extend((blocks[key]["text"] for key in anchor.block_ids))
            elif (
                not anchor.block_ids
                and anchor.quote
                and (normalized(anchor.quote) in normalized(pages.get(anchor.page, "")))
            ):
                texts.append(anchor.quote)
        semantic_anchor_present = bool(texts)
        if error.raw_text and any(
            (normalized(error.raw_text) in normalized(b["text"]) for b in visible_blocks)
        ):
            texts.append(error.raw_text)
        evidence = "\n".join(texts).casefold()
        role_words = {
            "stat": "\\bstat(?:istical)?\\b|统计",
            "sys": "\\bsys(?:tematic)?\\b|系统",
            "total": "\\btotal\\b|总误差|总不确定",
        }
        meaning_words = {
            "standard_uncertainty": "standard (?:uncertainty|deviation|error)|\\bsigma\\b|σ|标准(?:不确定|差)",
            "expanded_uncertainty": "expanded uncertainty|coverage factor|扩展不确定",
            "confidence_interval": "confidence|置信",
            "credible_interval": "credible|posterior|可信|后验",
            "quantile_bounds": "quantile|percentile|分位",
        }
        updates = {}
        supported = set(error.semantic_support_fields) if semantic_anchor_present else set()
        if (
            "role" not in supported
            and error.role in role_words
            and (not positive_semantic_label(role_words[error.role], evidence, check_after=False))
        ):
            updates["role"] = "unspecified"
        if (
            "meaning" not in supported
            and error.meaning in meaning_words
            and (
                not semantic_anchor_present
                or not positive_semantic_label(meaning_words[error.meaning], evidence)
            )
        ):
            updates["meaning"] = "unspecified"
        if error.level_kind and (
            not error.level_raw_text
            or not any((normalized(error.level_raw_text) in normalized(text) for text in texts))
        ):
            updates.update(level_kind=None, level_values=[], level_raw_text=None)
        if updates:
            updates["reason"] = "source_uncertainty_label_not_established_in_supplied_evidence"
        checked.append(error.model_copy(update=updates))
    return proposal.model_copy(update={"errors": checked})
