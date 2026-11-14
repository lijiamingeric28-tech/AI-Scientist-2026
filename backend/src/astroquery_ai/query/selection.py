from astroquery_ai.runtime.codec import new_id


def resolve_explicit_selection(draft, property_ids, operation_id, *, keep_gaps=False):
    """A submitted catalog selection replaces the earlier property wording.

    It does not resolve unit/filter/other requests or claim lexical synonymy.
    """
    for request in draft['property_requests']:
        if request.get('resolution') in {'unsupported', 'ambiguous'}:
            request.update(resolution='superseded_by_explicit_selection', selected_property_ids=list(property_ids), operation_id=operation_id)
    for issue in draft['issues']:
        if (issue['kind'] == 'ambiguous_property' or not keep_gaps and
                issue['kind'] in {'unsupported_property', 'inapplicable_property'}) and not issue.get('requires_omission'):
            issue.update(status='resolved', resolution='explicit_catalog_selection_replaced_wording', operation_id=operation_id)


def resolve_property_requests(draft, parsed, operation_id, *, source_text=None, semantic=None):
    """Apply model candidates and explicit edits; labels never determine intent."""
    if semantic is None:
        from astroquery_ai.runtime.errors import DomainError
        raise DomainError('PROPERTY_MATCH_REQUIRED', '须先由模型选择适用库候选，不能按名称自动映射', 422)
    allowed = {b['property_id'] for b in draft['property_support']['bindings']}
    if any(c['property_id'] not in allowed for r in semantic['requests'] for c in r['candidates']):
        from astroquery_ai.runtime.errors import DomainError
        raise DomainError('PROPERTY_CANDIDATE_SCOPE', '候选不在当前适用库', 502)
    parsed = {**parsed, 'properties': semantic['requests'], 'property_operation': semantic['property_operation'],
              'conditions': semantic['conditions'], 'unknown_fragments': semantic['unknown_fragments']}
    previous_offered = (draft.get('model_property_selection') or draft.get('previous_model_property_selection') or {}).get('candidate_property_ids', [])
    offered = list(dict.fromkeys(c['property_id'] for r in semantic['requests'] for c in r['candidates']))
    requests, selected, issues = [], [], []
    mode = parsed["property_operation"]
    for prop in parsed["properties"]:
        candidates = [c['property_id'] for c in prop['candidates']]
        unique = prop['coverage'] == 'complete' and len(candidates) == 1 and prop['candidates'][0]['match'] == 'equivalent'
        if prop['coverage'] in {'partial', 'none'}:
            technical=bool(semantic.get('technical_batch_failures'))
            issues.append({'issue_id': new_id(),
                           'kind': 'property_selection_incomplete' if technical else 'unsupported_property',
                           'description': ('性质选择技术未完成，不能判断该要求在库中缺失：' if technical else '')+prop['gap'],
                           'request_text': prop['text'], 'uncovered_text': prop.get('uncovered_text'),
                           'requires_omission': not technical, 'status': 'open'})
        requests.append(
            {
                **prop,
                "candidate_property_ids": candidates,
                "resolution": "mapped"
                if unique
                else "ambiguous"
                if candidates
                else "unsupported",
            }
        )
        if unique:
            selected.extend(candidates)
        elif mode == "remove":
            matching = [i for i in draft["issues"] if i["description"] == prop["text"]]
            if not matching:
                issues.append(
                    {
                        "issue_id": new_id(),
                        "kind": "ambiguous_property",
                        "description": "无法确定要移除的请求：" + prop["text"],
                        "status": "open",
                    }
                )
            for issue in matching:
                issue.update(
                    status="resolved", resolution="explicit_user_removal", operation_id=operation_id
                )
        elif candidates and mode != 'show':
            issues.append(
                {
                    "issue_id": new_id(),
                    "kind": "ambiguous_property" if candidates else "unsupported_property",
                    "description": prop["text"],
                    "candidate_explanations": prop["candidates"],
                    "status": "open",
                }
            )
    if mode == "replace":
        draft["selected_property_ids"] = list(dict.fromkeys(selected))
        draft["property_requests"], draft["issues"] = requests, issues
    elif mode == "add":
        draft["selected_property_ids"] = list(
            dict.fromkeys([*draft["selected_property_ids"], *selected])
        )
        draft["property_requests"].extend(requests)
        draft["issues"].extend(issues)
    elif mode == "remove":
        draft["selected_property_ids"] = [
            pid for pid in draft["selected_property_ids"] if pid not in selected
        ]
        draft["issues"].extend(issues)
    elif mode == "clear":
        draft["selected_property_ids"], draft["property_requests"], draft["issues"] = [], [], []
    elif mode == "show":
        draft['selected_property_ids'] = []
        draft['property_requests'] = requests
        draft['issues'] = issues
        draft["issues"].append(
            {
                "issue_id": new_id(),
                "kind": "property_count",
                "description": "已展示模型提出的适用候选，请明确选择1至5项具体性质",
                "status": "open",
            }
        )
    for condition in parsed["conditions"]:
        draft["issues"].append(
            {
                "issue_id": new_id(),
                "kind": "unsupported_unit"
                if condition.get("kind") == "unit"
                else "unsupported_filter",
                "description": condition["text"],
                "status": "open",
            }
        )
    for unknown in parsed["unknown_fragments"]:
        draft["issues"].append(
            {
                "issue_id": new_id(),
                "kind": "unknown_request",
                "description": unknown["text"],
                "status": "open",
            }
        )
    for issue in draft["issues"]:
        if issue["status"] == "accepted_omission" and mode != "unchanged":
            issue["status"] = "open"
            issue.pop("acknowledgement_operation_id", None)
    if mode in {'add', 'unchanged', 'remove'}:
        offered = list(dict.fromkeys([*previous_offered, *offered]))
    draft['model_property_selection'] = {'policy': 'model-candidates/1', 'candidate_property_ids': offered,
        'requests': requests, 'source_text': source_text, 'support_hash': draft['property_support']['support_hash'],
        'target_id': draft['target']['target_id'], 'operation_id': operation_id}
    draft.pop('previous_model_property_selection', None)
    if not draft['selected_property_ids'] and not any(i['status'] == 'open' for i in draft['issues']):
        draft['issues'].append({'issue_id': new_id(), 'kind': 'property_count', 'status': 'open',
                               'description': '请说明想查的性质，或选择模型提出的1至5项候选'})
    return []
