"""Cross-check a paper proposal against its local original evidence."""
from __future__ import annotations
from astroquery_ai.science.measurements.admission_contracts import normalized
import re
import unicodedata
from astroquery_ai.runtime.codec import digest
from astroquery_ai.science.catalogs import identifier_typography
from .paper_evidence import page_blocks


def check_local_evidence(
    proposal,
    check,
    target,
    pages,
    receipt,
    *,
    visible_blocks=None,
    image_pages=None,
    require_quantity=False,
    require_units=False,
    property_binding=None,
):
    """Bind an independently returned interpretation to actual saved page text."""
    result = {
        "schema_version": "PaperAdmissionVerification/1",
        "proposal_hash": digest(proposal.model_dump(mode="json")),
        "state": "unresolved",
        "reason": "local_subject_or_result_evidence_unresolved",
        "check": check.model_dump(mode="json") if check else None,
        "attempt_id": receipt.get("attempt_id"),
        "context": [],
    }
    if check is None:
        return result
    if check.quantity_identity is not None:
        # These are original model-selected anchors, not evidence generated
        # from its prose explanation. They pass the same actual-page checks.
        check=check.model_copy(update={'quantity_evidence':[
            *check.quantity_identity.evidence,
            *(check.quantity_identity.estimator_identity.evidence if check.quantity_identity.estimator_identity else []),
            *check.quantity_evidence]})
    if proposal.page is not None and proposal.page not in pages:
        result["reason"] = "proposal_page_not_in_supplied_source"
        return result
    blocks = {
        item["block_id"]: item
        for item in (visible_blocks if visible_blocks is not None else page_blocks(pages))
    }
    info = proposal.source_quality
    requested = [*(info.raw_info if info else []), *(info.caution_quotes if info else [])]
    result["source_information_blocks"] = [
        blocks[key] for key in dict.fromkeys(requested) if key in blocks
    ]

    def resolve(anchor):
        if not anchor.block_ids:
            return anchor
        selected = [blocks.get(key) for key in anchor.block_ids]
        if any((item is None or item["page"] != anchor.page for item in selected)):
            return anchor.model_copy(update={"quote": None})
        return anchor.model_copy(update={"quote": "\n".join((item["text"] for item in selected))})

    check = check.model_copy(
        update={
            "subject_evidence": [resolve(a) for a in check.subject_evidence],
            "role_evidence": [resolve(a) for a in check.role_evidence],
            "context": [
                item.model_copy(update={"anchor": resolve(item.anchor)}) for item in check.context
            ],
            "quantity_evidence": [resolve(a) for a in check.quantity_evidence],
            "unit_evidence": [resolve(a) for a in check.unit_evidence],
            "review_issue": check.review_issue.model_copy(update={
                key: [resolve(a) for a in getattr(check.review_issue, key)]
                for key in ('scope_evidence', 'support_evidence', 'counter_evidence')
            }) if check.review_issue else None,
            "subject_link": check.subject_link.model_copy(
                update={
                    "local_evidence": [resolve(a) for a in check.subject_link.local_evidence],
                    "scope_evidence": [resolve(a) for a in check.subject_link.scope_evidence],
                    "counter_evidence": [resolve(a) for a in check.subject_link.counter_evidence],
                }
            )
            if check.subject_link
            else None,
        }
    )
    result["check"] = check.model_dump(mode="json")

    def anchored(anchor):
        if not anchor.quote or anchor.page not in pages:
            return False
        if anchor.block_ids:
            return all(
                (key in blocks and blocks[key]["page"] == anchor.page for key in anchor.block_ids)
            )
        if image_pages is not None and anchor.page not in image_pages:
            return any(
                (
                    anchor.page == block["page"]
                    and normalized(anchor.quote) in normalized(block["text"])
                    for block in blocks.values()
                )
            )
        return normalized(anchor.quote) in normalized(pages[anchor.page])

    subject_ok = bool(check.subject_evidence) and all(map(anchored, check.subject_evidence))
    role_ok = bool(check.role_evidence) and all(map(anchored, check.role_evidence))
    if (require_quantity and property_binding and check.subject=='target' and check.quantity_match=='exact'
            and check.unit_match=='exact' and check.native_unit and check.unit_evidence
            and all(map(anchored,check.unit_evidence))):
        from astroquery_ai.science.native_dimensions import contradiction
        conflict=contradiction({'name':proposal.column or 'original_source_coordinate',
            'datatype':'double','unit_text':check.native_unit},property_binding['output_profile'],proposal.representation)
        if conflict:
            result.update(state='rejected',reason='source_coordinate_conflicts_with_selected_measurand',
                          coordinate_consistency=conflict,
                          model_quantity_verdict_retained=check.quantity_match)
            return result
    if check.value_location_kind == "plot" and role_ok:
        result.update(state="rejected", reason="value_only_reported_inside_figure")
        return result
    if check.result_role == "not_reported" and role_ok:
        result.update(state="rejected", reason="value_not_reported_in_source_scope")
        return result
    if role_ok and check.result_role in {"assumption", "calibration_constant", "rejected_solution"}:
        result.update(state="rejected", reason="not_an_eligible_reported_measurement")
        return result
    if check.review_issue:
        issue = check.review_issue
        actions = {choice.action for choice in issue.choices}
        anchors = [*issue.scope_evidence, *issue.support_evidence, *issue.counter_evidence]
        # A genuine ambiguity must be grounded in this candidate's actual source
        # scope. Known exclusions still take precedence over a proposed question.
        excluded = check.subject == 'other' or check.quantity_match == 'different'
        valid = (not excluded and all(map(anchored, anchors))
                 and any(a.page == proposal.page for a in anchors)
                 and 'unable' in actions and len(actions) == len(issue.choices)
                 and not (issue.issue_kind == 'unit_semantics' and 'confirm' in actions))
        if valid:
            result.update(reason='scientific_ambiguity', review_issue=issue.model_dump(mode='json'))
            return result
        result['review_issue_validation'] = 'evidence_or_options_invalid'
        if not excluded:
            result['reason'] = 'review_issue_evidence_or_options_invalid'
            return result
    if (proposal.value.kind in {'real', 'integer', 'interval'}
            and check.subject != 'other' and check.quantity_match != 'different'):
        unit_grounded = bool(check.unit_evidence) and all(map(anchored, check.unit_evidence))

        def incompatible_declared_units():
            """Format an evidenced contradiction, never guess the right unit."""
            if not (unit_grounded and check.native_unit and proposal.unit
                    and check.subject == 'target' and check.quantity_match == 'exact'
                    and any(normalized(check.native_unit) in normalized(a.quote or '') for a in check.unit_evidence)):
                return False
            from astroquery_ai.science.units import parse_unit
            try:
                conflict = not parse_unit(check.native_unit).is_equivalent(parse_unit(proposal.unit))
            except (ValueError, TypeError):
                return False
            if not conflict:
                return False
            result.update(reason='scientific_ambiguity', review_issue={
                'issue_kind': 'unit_semantics',
                'issue_key': 'incompatible-source-units-' + digest({'native': check.native_unit,
                    'claimed': proposal.unit, 'anchors': [a.model_dump(mode='json') for a in check.unit_evidence]}),
                'question': f'原件此处声明单位“{check.native_unit}”，当前候选使用“{proposal.unit}”，两者物理维度不相容。应不采用当前解释，还是保留未决？',
                'undecided_fact': '现成材料未能证明可将原件单位改为当前候选单位；不得凭常识猜改。',
                'scope_evidence': [a.model_dump(mode='json') for a in check.unit_evidence],
                'support_evidence': [a.model_dump(mode='json') for a in check.unit_evidence],
                'counter_evidence': [], 'correction_types': [],
                'choices': [{'action': 'not_supported', 'label': '不采用当前解释', 'impact': '这条候选不准入，原件和原报仍保留。'},
                            {'action': 'unable', 'label': '无法判断', 'impact': '保留未决候选，不输出猜测的规范值。'}],
                'generated_from': 'independent_native_unit_evidence_and_deterministic_unit_check',
            })
            return True

        if incompatible_declared_units():
            return result
        if unit_grounded and check.unit_match == 'exact' and check.native_unit and proposal.unit:
            if normalized(check.native_unit) != normalized(proposal.unit):
                from astroquery_ai.science.units import parse_unit
                try:
                    if parse_unit(check.native_unit) != parse_unit(proposal.unit):
                        result.update(reason='native_unit_contradiction', native_unit=check.native_unit,
                                      claimed_unit=proposal.unit)
                        return result
                except (ValueError, TypeError):
                    result.update(reason='native_unit_declaration_unresolved', native_unit=check.native_unit,
                                  claimed_unit=proposal.unit)
                    return result
        if check.unit_match == 'different' and unit_grounded:
            result.update(reason='native_unit_contradiction', native_unit=check.native_unit,
                          unit_evidence=[a.model_dump(mode='json') for a in check.unit_evidence])
            return result
        from astroquery_ai.science.unit_declarations import intrinsic_count_binding
        count_coordinate=(property_binding is not None and intrinsic_count_binding(property_binding)
            and proposal.unit is None and proposal.representation=='linear'
            and check.unit_match=='not_applicable' and check.native_unit is None
            and check.quantity_match=='exact' and bool(check.quantity_evidence) and all(map(anchored,check.quantity_evidence)))
        if count_coordinate:
            result['intrinsic_count_coordinate']={'kind':'source_evidenced_count','native_unit_literal':None,
                'quantity_evidence':[a.model_dump(mode='json') for a in check.quantity_evidence]}
        profile=(property_binding or {}).get('output_profile',{})
        dimensionless_coordinate=(profile.get('unit',{}).get('kind')=='dimensionless'
            and profile.get('representation',{}).get('kind')==proposal.representation
            and proposal.representation in {'log10','ln'} and proposal.unit is None
            and check.native_unit is None and check.unit_match=='not_applicable'
            and check.quantity_match=='exact' and bool(check.quantity_evidence)
            and all(map(anchored,check.quantity_evidence)))
        if dimensionless_coordinate:
            result['dimensionless_native_coordinate']={'kind':'source_evidenced_log_ratio',
                'raw_unit_literal':None,'quantity_evidence':[a.model_dump(mode='json') for a in check.quantity_evidence]}
        if require_units and not count_coordinate and not dimensionless_coordinate and (check.unit_match != 'exact' or not check.native_unit or not unit_grounded):
            result['reason'] = 'native_unit_not_verified'
            return result
    if require_quantity:
        if (
            check.quantity_match == "different"
            and check.quantity_evidence
            and all(map(anchored, check.quantity_evidence))
        ):
            result.update(state="rejected", reason="different_reported_measurand")
            return result
        if (
            check.quantity_match != "exact"
            or not check.quantity_evidence
            or (not all(map(anchored, check.quantity_evidence)))
        ):
            result["reason"] = "source_quantity_identity_unresolved"
            return result

    def identity_normalized(value):
        return normalized(identifier_typography(value))

    aliases = {
        identity_normalized(value) for value in [target["main_id"], *target.get("aliases", [])]
    }
    printed = normalized(check.printed_subject or "")
    identity_printed = identity_normalized(check.printed_subject or "")
    target_name = (
        identity_printed in aliases
        or any(
            (
                alias.startswith("PSR ") and identity_normalized(alias[4:]) == identity_printed
                for alias in [target["main_id"], *target.get("aliases", [])]
            )
        )
        if printed
        else False
    )
    footnote_context = None
    if not target_name and proposal.location_kind == "table":
        annotated = re.fullmatch("(.+?)([*†‡]{1,3})", (check.printed_subject or "").strip())
        if annotated:
            base, marker = annotated.groups()
            known = aliases | {
                identity_normalized(name[4:])
                for name in [target["main_id"], *target.get("aliases", [])]
                if name.startswith("PSR ")
            }
            subject_pages = {a.page for a in check.subject_evidence if anchored(a)}
            declaration = next(
                (
                    block
                    for block in blocks.values()
                    if block["page"] in subject_pages
                    and re.search(
                        "(?:label(?:l)?ed|marked|denoted|flagged)\\s+(?:with|by)\\s+(?:a\\s+)?"
                        + re.escape(marker),
                        block["text"],
                        re.I,
                    )
                ),
                None,
            )
            if identity_normalized(base) in known and declaration:
                target_name = True
                result["subject_annotation"] = {
                    "kind": "source_declared_footnote",
                    "base_identifier": base,
                    "marker": marker,
                    "printed_identifier_unchanged": check.printed_subject,
                    "declaration": declaration,
                }
                footnote_context = {
                    "kind": "source_caution",
                    "text": declaration["text"],
                    "anchor": {
                        "page": declaration["page"],
                        "block_ids": [declaration["block_id"]],
                        "quote": declaration["text"],
                    },
                }
    if not target_name and re.fullmatch("\\d{4}[+-]\\d{2,4}", printed):
        headers = "\n".join((a.quote or "" for a in check.subject_evidence))
        for prefix in ("B", "J"):
            namespace = f"(?:PSR\\s*{prefix}\\b|Pulsar\\s*\\(\\s*{prefix}[–−-]?\\s*\\))"
            if re.search(namespace, headers, re.I) and (
                normalized(prefix + printed) in aliases
                or normalized("PSR " + prefix + printed) in aliases
            ):
                target_name = True
                result["subject_namespace"] = {"prefix": prefix, "origin": "literal_table_header"}
    named_in_evidence = bool(printed) and any(
        (
            anchor.quote and identity_printed in identity_normalized(anchor.quote)
            for anchor in check.subject_evidence
        )
    )
    if not named_in_evidence and (check.printed_subject or "").startswith("PSR "):
        bare_name = identity_normalized(check.printed_subject[4:])
        if any(
            (
                anchor.quote and bare_name in identity_normalized(anchor.quote)
                for anchor in check.subject_evidence
            )
        ):
            named_in_evidence = True
            result["subject_display_prefix"] = {
                "prefix": "PSR ",
                "source_omits_display_prefix": True,
            }
    if not named_in_evidence:
        parts = re.fullmatch("(?:psr)?([bj])(\\d{4}[+-]\\d{2,4})", printed)
        if parts:
            prefix, cell = parts.groups()
            headers = "\n".join((a.quote or "" for a in check.subject_evidence))
            namespace = f"(?:PSR\\s*{prefix}\\b|Pulsar\\s*\\(\\s*{prefix}[–−-]?\\s*\\))"
            if re.search(namespace, headers, re.I) and cell in normalized(headers):
                named_in_evidence = True
                result["subject_namespace"] = {
                    "prefix": prefix.upper(),
                    "origin": "literal_table_header_and_cell",
                    "printed_cell": cell,
                }
    value_pages = {
        a.page
        for a in [
            *check.role_evidence,
            *check.quantity_evidence,
            *(check.subject_link.local_evidence if check.subject_link else []),
        ]
        if anchored(a) and (proposal.page is None or a.page == proposal.page)
    }
    directly_local = named_in_evidence and any(
        (
            anchored(a)
            and a.page in value_pages
            and a.quote
            and (
                identity_printed in identity_normalized(a.quote)
                or (
                    (check.printed_subject or "").startswith("PSR ")
                    and identity_normalized(check.printed_subject[4:])
                    in identity_normalized(a.quote)
                )
            )
            for a in check.subject_evidence
        )
    )
    if named_in_evidence and result.get("subject_namespace"):
        directly_local = any(
            (anchored(a) and a.page in value_pages for a in check.subject_evidence)
        )
    link = check.subject_link
    if (
        check.subject == "other"
        and subject_ok
        and role_ok
        and link
        and (link.relation == "other")
        and all(
            (
                anchored(a)
                for a in [*link.local_evidence, *link.scope_evidence, *link.counter_evidence]
            )
        )
        and any((a.page in value_pages for a in link.local_evidence))
    ):
        result.update(
            state="rejected",
            reason="different_local_subject",
            subject_link=link.model_dump(mode="json"),
        )
        return result
    contextual_binding = bool(
        link
        and link.relation == check.subject
        and (link.method != 'evidenced_alias' or any(
            identity_printed and a.quote and identity_printed in identity_normalized(a.quote)
            for a in link.scope_evidence))
        and all(
            (
                anchored(a)
                for a in [*link.local_evidence, *link.scope_evidence, *link.counter_evidence]
            )
        )
        and any((a.page in value_pages for a in link.local_evidence))
    )
    if contextual_binding:
        result["subject_link"] = link.model_dump(mode="json")
        # The independent interpreter establishes the local relationship from
        # cited scope/local/counter evidence. Method labels describe the proof;
        # no literal alias spelling can substitute for or veto that judgment.
        target_name = check.subject == 'target'
        result['identity_authority']='independent_semantics_with_verified_source_anchors'
    if not (subject_ok and role_ok and (directly_local or contextual_binding)):
        return result
    if contextual_binding:
        result["subject_binding"] = "evidenced_semantic_scope"
    if check.subject == "other":
        result.update(state="rejected", reason="different_local_subject")
    elif check.result_role in {"assumption", "calibration_constant", "rejected_solution"}:
        result.update(state="rejected", reason="not_an_eligible_reported_measurement")
    elif (
        check.subject == "target"
        and target_name
        and (check.result_role in {"reported_result", "adopted_measurement"})
    ):
        value_texts = [proposal.raw_value]
        if proposal.value.kind in {"real", "integer"}:
            value_texts.append(str(proposal.value.value))

        def literal_in(value, text):
            if proposal.value.kind in {"real", "integer"}:
                return (
                    re.search(
                        "(?<![\\d.])" + re.escape(value) + "(?![\\d.])",
                        unicodedata.normalize("NFKC", text).replace("−", "-"),
                    )
                    is not None
                )
            return normalized(value) in normalized(text)

        value_anchors = [
            a
            for a in [
                *check.role_evidence,
                *(
                    check.quantity_evidence
                    if require_quantity and check.quantity_match == "exact"
                    else []
                ),
                *(link.local_evidence if contextual_binding else []),
            ]
            if proposal.page is None or a.page == proposal.page
        ]
        located = any(
            (a.quote and literal_in(value, a.quote) for value in value_texts for a in value_anchors)
        )
        if (
            not located
            and proposal.page in pages
            and (image_pages is None or proposal.page in image_pages)
        ):
            literal = next(
                (value for value in value_texts if literal_in(value, pages[proposal.page])), None
            )
            if literal is not None:
                located = True
                result["value_location"] = {
                    "granularity": "page",
                    "page": proposal.page,
                    "literal": literal,
                    "method": "server_literal_in_supplied_full_page",
                }
        if located:
            result.update(state="passed", reason="local_subject_and_result_role_checked")
    result["excluded_context"] = [
        item.model_dump(mode="json")
        for item in check.context
        if item.subject_scope in {"other", "unresolved"}
        or item.property_scope in {"other", "unresolved"}
    ]
    result["context"] = [
        item.model_dump(mode="json")
        for item in check.context
        if anchored(item.anchor)
        and item.subject_scope not in {"other", "unresolved"}
        and (item.property_scope not in {"other", "unresolved"})
    ]
    if footnote_context and footnote_context not in result["context"]:
        result["context"].append(footnote_context)
    return result
