"""Read-only task knowledge projections; saved inputs are not sentence citations."""
from copy import deepcopy

from astroquery_ai.runtime.codec import content_hash, digest, loads
from astroquery_ai.runtime.errors import DomainError


def _properties(delivery, spec):
    rows = spec.get('properties') or delivery.get('definitions') or []
    return {row['property_id']: row.get('definition', {}).get('name_cn') or row.get('name') or row['property_id']
            for row in rows}


def _references(value, available):
    if isinstance(value, str):
        return {value} & available
    if isinstance(value, dict):
        return set().union(*(_references(v, available) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_references(v, available) for v in value)) if value else set()
    return set()


def historical_knowledge_context(repo, conn, source_task, delivery, spec, *, before=None):
    """Aggregate only saved fragments within an already validated delivery scope.

    None is the live-current read. Sealed, historical and replay callers must
    pass their visible cutoff; this helper never consults a current library.
    """
    from astroquery_ai.science.material_summaries import _identity

    names = _properties(delivery, spec)
    fragments = {}
    input_occurrences = 0

    def add(block, pids, usage, material=None):
        if not isinstance(block, dict) or not isinstance(block.get('claim'), dict):
            return
        cid = block['claim'].get('claim_id')
        if not cid:
            return
        # A saved input can contain a different archived revision of one claim.
        # Keep both exact texts instead of silently overwriting either version.
        key = cid, content_hash(block)
        if key not in fragments:
            own = deepcopy(block)
            own['saved_fragment_sha256'] = block.get('content_sha256') or content_hash(block)
            own.setdefault('entry_id', block.get('theory_id') or cid)
            own.update(property_ids=[], usage=[], material_ids=[], origin='historical_saved_basis')
            fragments[key] = own
        own = fragments[key]
        own['property_ids'] = sorted(set(own['property_ids']) | set(pids))
        own['usage'] = sorted(set(own['usage']) | {usage})
        if material and material not in own['material_ids']:
            own['material_ids'].append(material)

    report = delivery.get('insight_report')
    if not isinstance(report, dict):
        # Exact saved report reference first; never call the theory enrichment
        # performed by the public historical insights adapter.
        ref = (delivery.get('insight') or {}).get('report_ref')
        if ref:
            meta = conn.execute("SELECT created_at FROM objects WHERE task_id=? AND kind='insight' "
                                "AND object_id=? AND version=?", (source_task, ref['id'], ref['version'])).fetchone()
            if meta and (before is None or meta[0] <= before):
                report = repo.object(conn, source_task, 'insight', ref['id'], ref['version'])
    if isinstance(report, dict):
        if report.get('schema_version') == 'InsightBundle/1':
            report = report.get('property_report') or {}
        blocks = report.get('knowledge_blocks') or []
        available = {b.get('claim', {}).get('claim_id') for b in blocks}
        associations = {}
        for card in [*report.get('cards', []), *report.get('units', [])]:
            pid = card.get('property_id')
            if pid in names:
                for cid in _references(card, available):
                    associations.setdefault(cid, set()).add(pid)
        for block in blocks:
            cid = block.get('claim', {}).get('claim_id')
            pids = associations.get(cid, set()) | (set(block.get('property_ids') or []) & names.keys())
            add(block, pids, 'saved_report')

    rows = conn.execute(
        "SELECT s.object_id,s.payload FROM objects s WHERE s.task_id=? AND s.kind='material_summary' "
        "AND (? IS NULL OR s.created_at<=?) AND s.version=(SELECT max(i.version) FROM objects i "
        "WHERE i.task_id=s.task_id AND i.kind=s.kind AND i.object_id=s.object_id "
        "AND (? IS NULL OR i.created_at<=?)) ORDER BY s.object_id",
        (source_task, before, before, before, before))
    for row in rows:
        saved = loads(row[1])
        pid, mid = saved.get('property_id'), saved.get('material_id')
        if (saved.get('snapshot_ref') != delivery['snapshot_ref'] or not pid or not mid
                or row[0] != _identity(delivery, mid, pid) or pid not in names):
            continue
        basis = saved.get('basis') or {}
        if basis.get('property_id') not in {None, pid}:
            continue
        for block in basis.get('knowledge') or []:
            input_occurrences += 1
            add(block, [pid], 'saved_input', mid)

    entries = list(fragments.values())
    for entry in entries:
        entry['material_ids'].sort()
        entry['content_sha256'] = content_hash(entry)
    props = []
    for pid, name in names.items():
        selected = [e for e in entries if pid in e['property_ids']]
        props.append({'property_id': pid, 'name': name,
                      'state': 'conditional' if selected and all(e.get('conditions') for e in selected)
                      else 'matched' if selected else 'missing',
                      'entry_ids': list(dict.fromkeys(e.get('entry_id') or e['claim']['claim_id'] for e in selected)),
                      'reason': None if selected else 'historical_basis_not_recorded'})
    context = {'schema_version': 'TaskKnowledgeContext/1', 'origin': 'historical_saved_basis',
               'knowledge_release_ref': deepcopy(spec.get('knowledge_release')), 'library_version': None,
               'entries': entries, 'properties': props, 'input_occurrences': input_occurrences,
               'snapshot_ref': deepcopy(delivery['snapshot_ref']),
               'notice': '历史保存的报告引用或生成输入背景；输入背景不等于逐句引用。'}
    context['context_id'] = 'historical-knowledge-' + digest(context)
    context['content_sha256'] = content_hash(context)
    return context


def read_knowledge_context(application, conn, task_id, delivery_id, revision=None, *,
                           expected_revision=None, at_seq=None, sealed_only=False):
    """Validate publication/replay identity before constructing a conditional read."""
    service, repo = application.delivery, application.repository
    scope = service.display_scope(conn, task_id, delivery_id, revision, expected_revision=expected_revision,
                                  at_seq=at_seq, sealed_only=sealed_only)
    header = service.read_header(conn, task_id, delivery_id, scope['revision'])
    source = scope['source']
    task = repo.task(conn, source)
    query = loads(task['query_ref']) if task.get('query_ref') else None
    spec = repo.object(conn, source, 'confirmed_query', query['id'], query['version']) if query else {}
    reference = spec.get('knowledge_context_ref')
    from astroquery_ai.science.task_knowledge import enabled
    if enabled(spec) and not reference:
        raise DomainError('TASK_KNOWLEDGE_MISSING', '此任务缺少已固定的知识快照', 409)
    if reference:
        from astroquery_ai.science.task_knowledge import load
        bound = scope['summary_before']
        meta = conn.execute("SELECT created_at FROM objects WHERE task_id=? AND kind='task_knowledge' "
                            "AND object_id=? AND version=?", (source, reference['id'], reference['version'])).fetchone()
        if not meta or bound is not None and meta[0] > bound:
            raise DomainError('TASK_KNOWLEDGE_SCOPE', '此时点没有该任务知识快照', 409)
        context, origin = load(repo, conn, source, spec), 'task_snapshot'
    else:
        context = historical_knowledge_context(repo, conn, source, header, spec, before=scope['summary_before'])
        origin = 'historical_saved_basis'
    return {'delivery_id': delivery_id, 'delivery_revision': scope['revision'],
            'snapshot_ref': header['snapshot_ref'], 'context': context, 'origin': origin}, scope


def knowledge_reference_view(application, context, entry_id, claim_id, entry_hash):
    """Expand an exact saved citation without consulting the mutable library."""
    from astroquery_ai.science.task_knowledge import _checked
    _checked(context)
    selected = next((b for b in context.get('entries', [])
        if b.get('entry_id') == entry_id and b.get('claim', {}).get('claim_id') == claim_id
        and entry_hash in {b.get('content_sha256'), b.get('saved_fragment_sha256'),
            content_hash({k: v for k, v in b.items() if k != 'saved_fragment_sha256'})}), None)
    if selected is None:
        raise DomainError('KNOWLEDGE_REFERENCE_VERSION', '该引用不属于当前交付的知识版本', 409)
    block = deepcopy(selected)
    entry = deepcopy(block.get('raw_entry') or {})
    origin = 'saved_entry' if entry else 'saved_fragment'
    reference = block.get('knowledge_release_ref') or context.get('knowledge_release_ref')
    if not entry and reference:
        try:
            release = application.knowledge.load(reference)
            manifest = release['manifest']
            actual = {'id': manifest['release_id'], 'version': 1, 'content_sha256': manifest['content_sha256']}
            if actual != reference:
                raise DomainError('KNOWLEDGE_REFERENCE_VERSION', '知识发布版本不匹配', 409)
            candidate = next((e for e in release.get('author', {}).get('entries', [])
                              if e['entry_id'] == entry_id), None)
            for ordinal, part in enumerate((candidate or {}).get('blocks', [])):
                expected = 'kb-block-' + digest([reference['content_sha256'], entry_id, ordinal])
                if expected == claim_id and part.get('text') == block['claim'].get('text'):
                    entry, origin = deepcopy(candidate), 'same_release'
                    break
        except (DomainError, OSError, KeyError, TypeError, ValueError):
            # The saved fragment remains readable even when its release is absent.
            pass
    entry.setdefault('id', entry_id)
    entry.setdefault('name', block.get('title'))
    entry.setdefault('description', '\n\n'.join(p['text'] for p in entry.get('blocks', []))
                     or block.get('claim', {}).get('text'))
    for key in ('formula', 'conditions', 'parameters', 'sources', 'properties'):
        if key in block:
            entry.setdefault(key, deepcopy(block[key]))
    return {'entry': entry, 'block': block, 'claim': deepcopy(block['claim']),
            'read_only': True, 'expansion': origin, 'knowledge_release_ref': deepcopy(reference),
            'context_id': context.get('context_id'), 'library_version': context.get('library_version'),
            'entry_hash': entry_hash}
