"""Delivery-bound research views. All links come from saved identities and receipts."""

from collections import defaultdict

from astroquery_ai.runtime.codec import loads


def saved_before(conn, task_id, kind, cutoff):
    if not cutoff:
        return []
    rows = conn.execute(
        "SELECT o.payload FROM objects o JOIN (SELECT object_id, MAX(version) version "
        "FROM objects WHERE task_id=? AND kind=? AND created_at<=? GROUP BY object_id) v "
        "ON o.object_id=v.object_id AND o.version=v.version WHERE o.task_id=? AND o.kind=?",
        (task_id, kind, cutoff, task_id, kind),
    )
    return [loads(row[0]) for row in rows]


def historical_insights(conn, task_id, body, cutoff):
    if not cutoff:
        return []
    matches = {}
    for row in conn.execute("SELECT object_id,payload FROM objects WHERE task_id=? AND kind='insight' "
                            "AND created_at<=? ORDER BY created_at DESC,version DESC", (task_id, cutoff)):
        item = loads(row[1])
        if item.get('delivery_id') == body['delivery_id'] and item.get('snapshot_ref') == body['snapshot_ref']:
            matches.setdefault(row[0], item)
    return list(matches.values())


def process_facts(conn, task_id, cutoff):
    preparations = saved_before(conn, task_id, 'material_preparation', cutoff)
    return {
        'preparation': max(preparations, key=lambda item: item.get('revision', 0), default={}),
        'reading': saved_before(conn, task_id, 'reading_batch_state', cutoff),
    }


def review_details(conn, task_id, body):
    # Only answers frozen into this delivery may supply question/answer details.
    result = {}
    for answer in body.get('provenance_bundle', {}).get('human_answers', []):
        row = conn.execute('SELECT payload FROM reviews WHERE task_id=? AND review_id=?',
                           (task_id, answer['review_id'])).fetchone()
        if not row:
            continue
        question = loads(row[0])
        if question.get('revision') != answer.get('review_revision') or question.get('basis_hash') != answer.get('basis_hash'):
            continue
        result[answer['answer_id']] = {
            key: question.get(key) for key in ('question', 'title', 'choices', 'review_id', 'revision')
        }
    return result


def activities(body, difference=None, reviews=None):
    bundle = body.get('provenance_bundle', {})
    native = {m['measurement_id']: m for m in body['measurements']}
    candidates = {c['candidate_id']: c for c in bundle.get('candidate', [])}
    decisions = bundle.get('quality_decision', [])
    links = {link['candidate_ref']['id']: link for link in bundle.get('quality_candidate_link', [])}
    children = defaultdict(list)
    for cid, link in links.items():
        if link.get('parent_ref'):
            children[link['parent_ref']['id']].append(cid)
    measurements_by_candidate = defaultdict(list)
    for decision in decisions:
        mid = (decision.get('measurement_ref') or {}).get('id')
        if mid in native:
            measurements_by_candidate[decision['candidate_ref']['id']].append(mid)

    def descendants(cid):
        found, pending = set(), [cid]
        while pending:
            item = pending.pop()
            if item in found:
                continue
            found.add(item)
            pending.extend(children.get(item, []))
        return found

    result = []
    lineage_measurements = {cid: [mid for descendant in descendants(cid) for mid in measurements_by_candidate[descendant]]
                            for cid in candidates}
    causal_order = {}
    def order_candidates(cid):
        if cid in causal_order:
            return
        causal_order[cid] = len(causal_order) * 3
        for child in children.get(cid, []):
            order_candidates(child)
    for cid in candidates:
        if not (links.get(cid, {}).get('parent_ref')):
            order_candidates(cid)

    def add(key, kind, title, mids=(), **extra):
        mids = list(dict.fromkeys(mid for mid in mids if mid in native))
        first = native.get(mids[0], {}) if mids else {}
        source_ids = list(dict.fromkeys(native[mid]['source_ref']['id'] for mid in mids))
        result.append({'id': key, 'kind': kind, 'operation': title, 'measurement_ids': mids,
                       'property_id': (first.get('property_ref') or {}).get('id'),
                       'source_ids': source_ids, 'at': None, **extra})

    for decision in decisions:
        cid = decision['candidate_ref']['id']
        mids = lineage_measurements.get(cid, [])
        candidate = candidates.get(cid, {})
        if not mids:
            continue
        proposal = candidate.get('proposal', {})
        add('origin-' + cid, 'original', '原始候选形成', mids,
            before={'raw': proposal.get('raw_value'), 'unit': proposal.get('unit')},
            status='recorded', candidate_id=cid, parent_id=(links.get(cid, {}).get('parent_ref') or {}).get('id'))
    for action in bundle.get('quality_reextraction_action', []):
        parent = action['parent_candidate_ref']['id']
        related = descendants(parent) - {parent}
        mids = [mid for cid in related for mid in measurements_by_candidate[cid]]
        outcomes = [d['state'] for d in decisions if d['candidate_ref']['id'] in related]
        receipt = next((r for r in bundle.get('quality_reextraction_result', [])
                        if (r.get('parent_ref') or {}).get('id') == parent), {})
        add('reextract-' + parent, 'reextraction', '局部重提', mids,
            property_id=action.get('property_id'), source_ids=[action['source_id']],
            candidate_id=parent, successor_ids=sorted(related),
            before={k: candidates.get(parent, {}).get('proposal', {}).get(k) for k in ('raw_value', 'unit')},
            reason=action.get('problem', {}).get('reason'),
            value_check=action.get('problem', {}).get('value_match'),
            error_check=action.get('problem', {}).get('errors_match'),
            status='rechecked' if outcomes and all(x != 'reextraction_requested' for x in outcomes) else receipt.get('outcome', 'unknown'),
            conclusions=outcomes, candidate_count=receipt.get('candidate_count'))
    for decision in decisions:
        cid = decision['candidate_ref']['id']
        candidate = candidates.get(cid, {})
        proposal = candidate.get('proposal', {})
        evidence = candidate.get('evidence', {})
        assessment = decision.get('assessment') or {}
        source_check = assessment.get('assessment') or {}
        explanation = source_check.get('reason') or (assessment.get('source_quality') or {}).get('note')
        add('check-' + cid, 'quality', '原文核验', lineage_measurements.get(cid, []),
            candidate_id=cid, status=decision['state'], reason=explanation,
            before={'raw': proposal.get('raw_value'), 'unit': proposal.get('unit')},
            origin_locator={'task_id': body.get('task_id'), 'artifact_id': (evidence.get('artifact_ref') or {}).get('id'),
                            'page': evidence.get('locator', {}).get('page')},
            property_id=candidates.get(cid, {}).get('proposal', {}).get('property_id'),
            source_ids=[candidates.get(cid, {}).get('assembly_context', {}).get('source', {}).get('source_id')])
    for answer in bundle.get('human_answers', []):
        receipt = next((r for r in bundle.get('review_applications', []) if r.get('answer_id') == answer['answer_id']), {})
        mids = [r.get('measurement_id') for r in receipt.get('results', [])]
        mids += [mid for mid, m in native.items() if any(
            i.get('interpretation_id') == m['interpretation_ref']['id']
            and (i.get('human_answer_ref') or {}).get('id') == answer['answer_id']
            for i in bundle.get('interpretations', []))]
        add(answer['answer_id'], 'human', '人工判断与复检', mids,
            at=answer.get('received_at'), status=receipt.get('status', 'received'),
            reason=answer.get('reason'), outcome=answer.get('comparison_outcome') or answer.get('action'),
            simulation=answer.get('simulation', False), postcheck=receipt.get('postcheck'),
            question=(reviews or {}).get(answer['answer_id']), application_results=receipt.get('results', []))
    derived = {d['measurement_id']: d for d in body.get('derived', [])}
    changes = {c['after_ref']['id']: c for c in bundle.get('normalization_changes', [])}
    for mid, m in native.items():
        d = derived.get(mid, {})
        receipt = next((r for r in bundle.get('processing_receipts', []) if (r.get('input_ref') or {}).get('id') == mid), {})
        change = changes.get(d.get('derived_id'), {})
        ready = d.get('main_state') == 'ready'
        same = (d.get('scientific_operation') or {}).get('operation') == 'same_value_target'
        effect = 'no_change' if ready and same else 'converted' if ready and change else 'verified' if ready else 'not_run'
        if receipt.get('status') in {'failed', 'error'}:
            effect = 'failed'
        add('processing-' + mid, 'representation', '主值处理', [mid],
            status=effect, at=receipt.get('timestamp') or change.get('timestamp'),
            actual_change=bool(change) and not same,
            before={'raw': m.get('raw_value'), 'value': m.get('value'), 'unit': m.get('unit')},
            after={'value': d.get('value_typed'), 'coordinate_units': d.get('coordinate_units')} if ready else None,
            reason=receipt.get('reason'), validation=receipt.get('postcheck'),
            checks=receipt.get('checks', []), field_diff=change.get('field_diff', []),
            before_ref=change.get('before_ref') or receipt.get('input_ref'),
            after_ref=change.get('after_ref') or receipt.get('output_ref'))
        for component in (d.get('uncertainty_typed') or {}).get('components', []):
            add('uncertainty-' + mid + '-' + component['source_component_id'], 'uncertainty', '独立误差处理', [mid],
                at=receipt.get('timestamp'), status=component.get('status'),
                component_id=component['source_component_id'], output_component=component.get('output_component'))
    for group in body.get('archive_groups', []):
        add(group['group_id'], 'archive', '有据重复归档', [r['id'] for r in group['member_refs']],
            reason=group.get('reason'), status='archived')
    for check in (difference or {}).get('checks', body.get('comparison_checks', [])):
        pid = check.get('property_id')
        add('comparison-' + str(pid), 'comparison', '性质对照',
            [mid for mid, m in native.items() if m['property_ref']['id'] == pid],
            property_id=pid, status=check.get('state'), reason=check.get('reason'))
    for mid in native:
        add('delivery-' + mid, 'delivery', '进入科学快照', [mid], status='sealed',
            delivery_revision=body['revision'], snapshot_ref=body['snapshot_ref'])
    # Causal steps are explicit. No timestamp is invented for older objects.
    offsets = {'original': 0, 'quality': 1, 'reextraction': 2}
    result.sort(key=lambda item: causal_order.get(item.get('candidate_id'), len(causal_order) * 3) + offsets.get(item['kind'], 3))
    for index, item in enumerate(result):
        item['order'] = index
    return result


def enrich_materials(rows, body, facts, quality):
    bundle = body.get('provenance_bundle', {})
    candidates = bundle.get('candidate', [])
    names = {b['property_id']: b['definition']['name_cn'] for b in body['definitions']}
    pools = facts.get('preparation', {}).get('pools', {})
    completion = {m['material_id']: m for c in bundle.get('completion_scope', []) for m in c.get('materials', [])}
    extraction = next((c for c in (quality or {}).get('components', []) if c['key'] == 'extraction'), {})
    completed = {m['material_id']: m for m in extraction.get('materials', [])}
    for row in rows:
        wid = (row.get('work') or {}).get('work_id') or row.get('work_id') or row['source_id']
        mid = 'paper:' + wid
        scope = completion.get(mid, {})
        allocated = set((row.get('work') or {}).get('allowed_property_ids', []))
        allocated.update(r.get('property_id') for r in scope.get('ranges', []))
        assignments = []
        for pid, name in names.items():
            pool = pools.get(pid, {})
            is_allocated = pid in allocated
            own = [c for c in candidates if c.get('assembly_context', {}).get('source', {}).get('source_id') == row['source_id']
                   and c.get('proposal', {}).get('property_id') == pid]
            mids = [m['measurement_id'] for m in body['measurements'] if m['source_ref']['id'] == row['source_id'] and m['property_ref']['id'] == pid]
            if not (is_allocated or own or mids or wid in pool.get('evaluated', [])):
                continue
            reading = [r for r in facts.get('reading', []) if r.get('work_id') == wid and pid in r.get('property_ids', [])]
            assignments.append({'property_id': pid, 'name': name,
                'evaluated': wid in pool.get('evaluated', []) if pools else None,
                'eligible': (pool.get('decisions', {}).get(wid) or {}).get('decision') in {'relevant', 'possibly_relevant'} if pools else None,
                'acquired': wid in pool.get('acquired', []) if pools else bool(row.get('artifact')),
                'allocated': is_allocated, 'candidate_count': len(own), 'measurement_ids': mids,
                'read_pages': sorted({p for r in reading if r.get('coverage') == 'checked' for p in r.get('core_pages', [])}),
                'expected_pages': sorted({r['page'] for r in scope.get('ranges', []) if r.get('property_id') == pid and 'page' in r})})
        row['assignments'] = assignments
        row['reading_scope'] = completed.get(mid)
        row['attachment_ids'] = [a['material_id'] for a in rows if a.get('parent_material_id') == row['material_id']]
        if row.get('kind') == 'cited' or 'cited' in row.get('roles', []):
            row['citation_record_ids'] = list(dict.fromkeys(ref['measurement_id'] for ref in row.get('citations', []) if ref.get('measurement_id')))
    return rows


def coverage_matrix(body, quality, difference, insight, facts):
    bundle = body.get('provenance_bundle', {})
    rows = []
    checks = {c['property_id']: c for c in (difference or {}).get('checks', [])}
    decisions = bundle.get('quality_decision', [])
    roots = bundle.get('quality_candidate_root', [])
    derived = {d['measurement_id']: d for d in body.get('derived', [])}
    cards = {c['property_id']: c for c in (insight or {}).get('cards', [])}
    pools = facts.get('preparation', {}).get('pools', {})
    evidence = {e['evidence_id']: e for e in body.get('evidence_index', [])}
    views = {v['evidence_id']: v for v in body.get('evidence_views', [])}
    for binding in body['definitions']:
        pid = binding['property_id']
        mids = [m['measurement_id'] for m in body['measurements'] if m['property_ref']['id'] == pid]
        root_ids = {r['root_id'] for r in roots if r['property_id'] == pid}
        concluded = {d['root_id'] for d in decisions if d['root_id'] in root_ids and d['state'] in {'supported', 'not_applicable', 'not_supported'}}
        clean = sum(derived.get(mid, {}).get('main_state') == 'ready' for mid in mids)
        reading = [r for r in facts.get('reading', []) if pid in r.get('property_ids', [])]
        read_ranges = {(r.get('work_id'), page) for r in reading if r.get('coverage') == 'checked' for page in r.get('core_pages', [])}
        expected = {(m['material_id'].removeprefix('paper:'), r['page']) for scope in bundle.get('completion_scope', [])
                    for m in scope.get('materials', []) for r in m.get('ranges', []) if r.get('property_id') == pid and 'page' in r}
        readable = (quality or {}).get('readable_per_property', {}).get(pid)
        material_reached = pools.get(pid, {}).get('close_reason') == 'readable_target_reached'
        card = cards.get(pid)
        read_failed = any(r.get('coverage') in {'failed', 'technical_failure'} for r in reading)
        quality_failed = any(d['root_id'] in root_ids and d['state'] == 'technical_failure' for d in decisions)
        clean_failed = any(derived.get(mid, {}).get('status') in {'failed', 'error'} for mid in mids)
        def cell(state, count=None, total=None, unit=None):
            return {'state': state, 'count': count, 'total': total, 'unit': unit}
        cells = {
            'materials': cell('complete' if material_reached else 'partial' if readable else 'not_checked', readable, None, '篇可读正文'),
            'extraction': cell('complete' if expected and expected <= read_ranges else 'partial' if read_ranges else 'technical_failure' if read_failed else 'incomplete' if reading else 'not_checked', len(read_ranges) if reading else None, len(expected) if expected else None, '个核心页范围'),
            'quality': cell('complete' if root_ids and root_ids <= concluded else 'partial' if concluded else 'technical_failure' if quality_failed else 'incomplete' if root_ids else 'not_checked', len(concluded) if root_ids else None, len(root_ids) if root_ids else None, '项根问题'),
            'cleaning': cell('complete' if mids and clean == len(mids) else 'partial' if clean else 'technical_failure' if clean_failed else 'not_run', clean, len(mids), '条处理就绪或核验不变'),
            'comparison': cell('complete' if checks.get(pid, {}).get('state') == 'checked' else 'incomplete' if pid in checks else 'not_checked', 1 if checks.get(pid, {}).get('state') == 'checked' else 0, 1, '项性质核对'),
            'insights': cell('complete' if card and card.get('status') == 'generated' else 'technical_failure' if card and card.get('status') == 'failed' else 'not_applicable' if insight and insight.get('generation_enabled') is False else 'pending' if insight and insight.get('status') == 'pending' else 'not_checked', 1 if card and card.get('status') == 'generated' else None, 1, '项洞察'),
        }
        own = [m for m in body['measurements'] if m['measurement_id'] in mids]
        stats = {
            'page': sum(any(evidence.get(r['id'], {}).get('locator', {}).get('page') for r in m.get('evidence_refs', [])) for m in own),
            'excerpt': sum(any(evidence.get(r['id'], {}).get('raw_text') for r in m.get('evidence_refs', [])) for m in own),
            'region': sum(any(p.get('bbox') for r in m.get('evidence_refs', []) for p in views.get(r['id'], {}).get('points', [])) for m in own) if body.get('evidence_views') is not None else None,
            'table': sum(any(views.get(r['id'], {}).get('kind') == 'table' for r in m.get('evidence_refs', [])) for m in own) if body.get('evidence_views') is not None else None,
        }
        rows.append({'property_id': pid, 'name': binding['definition']['name_cn'], 'measurement_ids': mids, 'cells': cells, 'evidence': stats})
    return rows
