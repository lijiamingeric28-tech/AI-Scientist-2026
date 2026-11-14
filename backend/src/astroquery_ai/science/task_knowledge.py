"""Task-scoped knowledge fragments, sealed before the confirmed query hash.

The candidate selection view deliberately has no science snapshot: actual facts
are supplied only by delivery generation. Supplemental knowledge is background,
never a replacement for the exact formal definition/profile/rule binding.
"""
from copy import deepcopy
from contextlib import nullcontext

from astroquery_ai.runtime.codec import content_hash, digest
from astroquery_ai.runtime.errors import DomainError
from .author_knowledge import assemble_insight_input, verified_types
from .knowledge_projection import property_key

MODE = 'research-workbench/2'
SCHEMA = 'TaskKnowledgeContext/1'
KIND = 'task_knowledge'


def enabled(spec):
    return spec.get('run_policy', {}).get('insights', {}).get('presentation') == MODE


def _checked(context):
    if (not isinstance(context, dict) or context.get('schema_version') != SCHEMA
            or context.get('content_sha256') != content_hash(context)):
        raise DomainError('TASK_KNOWLEDGE_HASH', '任务知识快照校验失败', 409)
    for entry in context.get('entries', []):
        if entry.get('content_sha256') != content_hash(entry):
            raise DomainError('TASK_KNOWLEDGE_HASH', '任务知识片段校验失败', 409)
    return context


def _seal(entry):
    result = deepcopy(entry)
    result['content_sha256'] = content_hash(result)
    return result


def capture(app, spec):
    """Copy only exact-bound formal blocks and property-relevant background."""
    properties = spec.get('properties', [])
    entries, issues = [], []
    formal_state = 'available'
    reference = deepcopy(spec.get('knowledge_release'))
    if reference:
        try:
            release = app.knowledge.load(reference)
            manifest = release['manifest']
            actual = {'id': manifest['release_id'], 'version': 1, 'content_sha256': manifest['content_sha256']}
            if actual != reference:
                raise DomainError('TASK_KNOWLEDGE_RELEASE', '任务正式知识发布版本不匹配', 409)
            # Exact binding selection only. None explicitly means no facts snapshot.
            selection = {'snapshot_ref': None, 'definitions': properties,
                         'measurements': [], 'derived': [], 'contexts': [], 'evidence_index': []}
            assembled = assemble_insight_input(selection, release['author'], spec=spec)
            issues.extend(deepcopy(assembled['inapplicable_bindings']))
            by_claim = {}
            for row in assembled['knowledge_candidates']:
                mapping = {key: deepcopy(value) for key, value in row.items() if key != 'cards'}
                for card in row['cards']:
                    for ordinal, block in enumerate(card['blocks']):
                        cid = 'kb-block-' + digest([manifest['content_sha256'], card['entry_id'], ordinal])
                        if cid not in by_claim:
                            by_claim[cid] = {'claim': {'claim_id': cid, 'text': block['text'], 'role': block['role']},
                                'entry_id': card['entry_id'], 'title': card['title'], 'conditions': deepcopy(card['conditions']),
                                'sources': [deepcopy(release['sources'][sid]) for sid in block['source_ids']],
                                'authoring_basis': block['basis'], 'origin': 'formal_release', 'property_ids': [],
                                'applicable_mappings': [], 'knowledge_release_ref': reference,
                                'applicability_state': 'conditional' if card['conditions'] else 'matched'}
                        item = by_claim[cid]
                        if row['property_id'] not in item['property_ids']: item['property_ids'].append(row['property_id'])
                        if mapping not in item['applicable_mappings']: item['applicable_mappings'].append(mapping)
            entries.extend(_seal(item) for item in by_claim.values())
        except DomainError as exc:
            if exc.code != 'KB_MISSING': raise
            formal_state = 'unavailable'; issues.append({'origin': 'formal_release', 'reason': exc.code})
        except (FileNotFoundError, PermissionError) as exc:
            formal_state = 'unavailable'; issues.append({'origin': 'formal_release', 'reason': type(exc).__name__})
        except (KeyError, TypeError, ValueError) as exc:
            raise DomainError('TASK_KNOWLEDGE_SCHEMA', '任务正式知识结构不可核验', 409) from exc
    else:
        formal_state = 'unavailable'; issues.append({'origin': 'formal_release', 'reason': 'release_not_pinned'})
    library_version = None
    background_state = 'available'
    store = getattr(app, 'user_knowledge', None)
    if store is not None:
        try:
            # One coherent overlay revision, including preference basis.
            with store._locked() if hasattr(store, '_locked') else nullcontext():
                candidates = store.list_entries(limit=-1)['items']
                library_version = getattr(store, 'revision', None)
                types = {value.casefold() for value in verified_types(spec)}
                for raw in candidates:
                    if raw.get('is_deleted'): continue
                    # Built-in author text is admitted only through its exact
                    # released binding above. An explicit overlay is separately
                    # identified user background, with its own conditions.
                    if raw.get('origin') == 'author_entry' and not (raw.get('is_user') or raw.get('is_override')):
                        continue
                    scopes = {str(value).casefold() for value in raw.get('entity_types', []) if value}
                    if scopes and not scopes.intersection(types): continue
                    keys = {property_key(value) for value in raw.get('properties', [])}
                    pids = [b['property_id'] for b in properties if property_key(b['property_id']) in keys]
                    if not pids: continue
                    block = deepcopy(store.to_knowledge_block(raw))
                    block.update(raw_entry=deepcopy(raw), property_ids=pids,
                        origin='user_background' if raw.get('is_user') or raw.get('is_override') else 'theory_background',
                        applicability_state='conditional' if raw.get('conditions') else 'matched',
                        preference_basis={key: deepcopy(raw.get(key)) for key in
                            ('preference', 'preferred', 'weight_boost', 'revision', 'library_revision')})
                    entries.append(_seal(block))
        except (DomainError, OSError, KeyError, TypeError, ValueError) as exc:
            background_state = 'unavailable'; issues.append({'origin': 'background', 'reason': getattr(exc, 'code', type(exc).__name__)})
    else:
        background_state = 'unavailable'; issues.append({'origin': 'background', 'reason': 'library_unavailable'})
    prop_states = []
    for binding in properties:
        pid = binding['property_id']; selected = [e for e in entries if pid in e['property_ids']]
        if selected:
            state = 'matched' if any(e['applicability_state'] == 'matched' for e in selected) else 'conditional'
            reason = 'exact_binding_or_explicit_property_background'
        else:
            state = 'unavailable' if 'unavailable' in {formal_state, background_state} else 'missing'
            reason = 'knowledge_unreadable' if state == 'unavailable' else 'no_exact_applicable_knowledge'
        prop_states.append({'property_id': pid, 'name': binding.get('display_name') or binding.get('definition', {}).get('name_cn') or pid,
            'state': state, 'entry_ids': list(dict.fromkeys(e['entry_id'] for e in selected)), 'reason': reason,
            'formal_state': formal_state, 'background_state': background_state})
    result = {'schema_version': SCHEMA, 'knowledge_release_ref': reference, 'library_version': library_version,
              'entries': entries, 'properties': prop_states, 'issues': issues,
              'selection_basis': 'confirmed_exact_bindings_and_explicit_property_scope',
              'facts_snapshot_ref': None, 'relationships': []}
    result['context_id'] = 'task-knowledge-' + digest(result)
    return _seal(result)


def pin(app, conn, tid, spec):
    if not enabled(spec): return None
    if spec.get('knowledge_context_ref'):
        load(app.repository, conn, tid, spec)
        return deepcopy(spec['knowledge_context_ref'])
    context = capture(app, spec)
    reference = app.repository.put_object(conn, tid, KIND, context['context_id'], 1, context)
    spec['knowledge_context_ref'] = deepcopy(reference)
    return deepcopy(reference)


def load(repo, conn, tid, spec):
    reference = spec.get('knowledge_context_ref')
    if not reference: return None
    context = repo.object(conn, tid, KIND, reference['id'], reference['version'])
    _checked(context)
    if context['context_id'] != reference['id'] or context['content_sha256'] != reference['content_sha256']:
        raise DomainError('TASK_KNOWLEDGE_HASH', '任务知识引用校验失败', 409)
    return deepcopy(context)


def blocks(context, property_id=None):
    if context is None: return []
    return deepcopy([entry for entry in _checked(context)['entries']
                     if property_id is None or property_id in entry.get('property_ids', [])])


class FrozenStore:
    """Existing knowledge-store API backed exclusively by copied task fragments."""
    def __init__(self, context):
        self._context = deepcopy(_checked(context))
        self._blocks = blocks(self._context)

    @property
    def by_id(self):
        return {b['entry_id']: deepcopy(b) for b in self._blocks}

    def get_entry(self, entry_id):
        for block in self._blocks:
            if entry_id in {block['entry_id'], block['claim']['claim_id']}:
                return deepcopy(block.get('raw_entry') or block)
        return None

    def to_knowledge_block(self, entry):
        if entry.get('claim'): return deepcopy(entry)
        eid = entry.get('id') or entry.get('entry_id')
        return deepcopy(next((b for b in self._blocks if b['entry_id'] == eid), None))

    def resolve_cached_block(self, block):
        cid = (block.get('claim') or {}).get('claim_id')
        candidates = [b for b in self._blocks if b['claim']['claim_id'] == cid]
        # A claim ID can occur in several archived inputs. Complete saved
        # fragments must resolve to their own content, never the first edition.
        exact = [b for b in candidates if content_hash(b) == content_hash(block)]
        if exact:
            return deepcopy(exact[0])
        if (block.get('claim') or {}).get('text') is not None:
            return None
        return deepcopy(candidates[0]) if len(candidates) == 1 else None

    def get_preferred_ids(self):
        return {b['entry_id'] for b in self._blocks if b.get('user_preferred') or b.get('user_preference') == 'preferred'}

    def search(self, field_names=None, entity_types=None, keywords=None, categories=None, top_k=5,
               user_only=False, preferred_only=False):
        fields = {property_key(value) for value in field_names or [] if value}
        entities = {str(value).casefold() for value in entity_types or [] if value}
        needles = [str(value).casefold() for value in keywords or [] if value]
        found = []
        for block in self._blocks:
            raw = block.get('raw_entry') or {}
            if fields and not fields.intersection(property_key(p) for p in block['property_ids']): continue
            if entities and raw.get('entity_types') and not entities.intersection(str(e).casefold() for e in raw['entity_types']): continue
            if categories and block.get('category') not in categories: continue
            if user_only and not block.get('is_user'): continue
            if preferred_only and not block.get('user_preferred'): continue
            text = (block['title'] + ' ' + block['claim']['text']).casefold()
            if not fields and needles and not any(n in text for n in needles): continue
            found.append(block)
        found.sort(key=lambda b: (bool(b.get('user_preferred')), b.get('weight_boost', 1)), reverse=True)
        return deepcopy(found if top_k < 0 else found[:top_k])

    def derive_network_relationships(self, field_names, top_relations=12):
        fields = set(field_names)
        return deepcopy([r for r in self._context.get('relationships', [])
                         if r.get('field_a') in fields and r.get('field_b') in fields][:top_relations])


def frozen_user_store(context):
    return FrozenStore(context) if context is not None else None


def frozen_theory_store(context):
    return FrozenStore(context) if context is not None else None
