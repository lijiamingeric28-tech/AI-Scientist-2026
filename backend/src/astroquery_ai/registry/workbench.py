"""Persistent registry drafts, effective read views and atomic version activation."""
from copy import deepcopy
from pathlib import Path
import os
import shutil
import sqlite3
import threading
from functools import wraps

from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads, new_id, utcnow
from astroquery_ai.runtime.errors import DomainError
from .workbench_projection import source_projection, apply_operations, ref, key
from .workspace_release import release_ref, knowledge_compatibility

KINDS = {'types', 'properties', 'bindings'}
IDENTITY = ('property_id', 'quantity_key', 'quantity_kind', 'scope', 'definition_qualifiers', 'value_schema')


def persistence_errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (sqlite3.Error, OSError) as exc:
            raise DomainError('WORKSPACE_PERSISTENCE_FAILED', '规范存储失败，未确认保存', 503) from exc
    return wrapped


class RegistryWorkbench:
    def __init__(self, registry, repository, knowledge=None):
        self.registry, self.repository, self.knowledge = registry, repository, knowledge
        self._projection_cache = {}
        self._view_cache = {}
        self._cache_lock = threading.RLock()

    def _base(self, reference):
        with self._cache_lock:
            return self._load_base(reference)

    def _load_base(self, reference):
        release = self.registry.load(reference['id'])
        if release_ref(release) != reference:
            raise DomainError('WORKSPACE_BASE_CHANGED', '基础发布内容不一致', 422)
        cache_key = reference['content_sha256']
        if cache_key not in self._projection_cache:
            self._projection_cache[cache_key] = source_projection(release)
        return release, self._projection_cache[cache_key]

    def _workspace(self, conn, identifier):
        row = conn.execute('SELECT payload FROM registry_workspaces WHERE workspace_id=?', (identifier,)).fetchone()
        if not row:
            raise DomainError('WORKSPACE_NOT_FOUND', '规范草稿不存在', 404)
        return loads(row[0])

    def get_workspace(self, identifier):
        with self.repository.read() as conn:
            return self._workspace(conn, identifier)

    @classmethod
    def _directory_item(cls, item):
        fields = ('id', 'name', 'label', 'status', 'revision', 'created_at', 'updated_at',
                  'published_at', 'base_bundle', 'base_bundle_id', 'bundle_id', 'registry_ref',
                  'knowledge_ref', 'capability_ref', 'release_id', 'active')
        return {k: cls._directory_item(item[k]) if k == 'base_bundle' else deepcopy(item[k])
                for k in fields if k in item}

    def list_workspaces(self, *, projection='full'):
        if projection not in {'full', 'directory'}:
            raise DomainError('INVALID_PROJECTION', '未知读取投影', 422)
        with self.repository.read() as conn:
            items = [loads(row[0]) for row in conn.execute('SELECT payload FROM registry_workspaces ORDER BY updated_at DESC')]
        drafts = [w for w in items if w['status'] == 'draft']
        return {'items': [self._directory_item(w) for w in drafts] if projection == 'directory' else drafts, 'total': len(drafts)}

    @persistence_errors
    def create_workspace(self, base_bundle_id=None):
        with self.repository.transaction() as conn:
            bundle = self.registry.active_bundle(conn)
            if base_bundle_id and base_bundle_id != bundle['id']:
                row = conn.execute('SELECT payload FROM registry_bundles WHERE bundle_id=?', (base_bundle_id,)).fetchone()
                if not row:
                    raise DomainError('BUNDLE_NOT_FOUND', '基础版本组合不存在', 404)
                bundle = loads(row[0])
            conn.execute('INSERT OR IGNORE INTO registry_bundles VALUES(?,?,?)', (bundle['id'], canonical(bundle), utcnow()))
            workspace = {'id': 'workspace_' + new_id(), 'revision': 1, 'status': 'draft',
                'base_bundle': bundle, 'operations': [], 'validation': None, 'created_at': utcnow()}
            self._save(conn, workspace, create=True)
        return {'success': True, 'workspace': workspace}

    def _save(self, conn, workspace, create=False):
        workspace['updated_at'] = utcnow()
        if create:
            conn.execute('INSERT INTO registry_workspaces VALUES(?,?,?,?)', (workspace['id'], workspace['revision'], canonical(workspace), workspace['updated_at']))
        else:
            conn.execute('UPDATE registry_workspaces SET revision=?,payload=?,updated_at=? WHERE workspace_id=?',
                         (workspace['revision'], canonical(workspace), workspace['updated_at'], workspace['id']))

    def _revision(self, workspace, expected):
        if workspace['status'] != 'draft':
            raise DomainError('WORKSPACE_READONLY', '已发布规范不可修改', 409)
        if type(expected) is not int or workspace['revision'] != expected:
            raise DomainError('WORKSPACE_CONFLICT', '规范草稿已变更，请重新读取', 409, revision=workspace['revision'])

    def _view(self, workspace_id=None, release_id=None):
        with self._cache_lock:
            return self._load_view(workspace_id, release_id)

    def _load_view(self, workspace_id=None, release_id=None):
        if workspace_id and release_id:
            raise DomainError('INVALID_VIEW', '草稿与历史版本不能同时指定', 422)
        workspace = self.get_workspace(workspace_id) if workspace_id else None
        bundle = self.registry.active_bundle()
        if workspace:
            reference = workspace['base_bundle']['registry_ref']
        elif release_id:
            release = self.registry.load(release_id); reference = release_ref(release)
        else:
            reference = bundle['registry_ref']
        release, base = self._base(reference)
        revision = workspace['revision'] if workspace else reference['content_sha256']
        knowledge_ref = workspace['base_bundle'].get('knowledge_ref') if workspace else release.get('workspace', {}).get('base_knowledge_ref', bundle.get('knowledge_ref'))
        cache_key = (reference['content_sha256'], workspace_id, revision, knowledge_ref and knowledge_ref['content_sha256'],
                     (workspace.get('validation') or {}).get('id') if workspace else None)
        cached = self._view_cache.get(cache_key)
        if cached:
            return cached[0], workspace, bundle, revision, release, cached[1]
        projection = apply_operations(base, workspace['operations']) if workspace else deepcopy(base)
        if workspace or not release.get('workspace'):
            from .user_execution import compile_execution
            _, execution_caps, _ = compile_execution(projection, release)
        else:
            # Published user authority comes only from its frozen manifest.
            # Legacy workspaces never acquire execution refs through a read.
            execution_caps = {entry['contract']['property_key']: {
                **deepcopy(entry['contract']['capabilities']), 'execution_ref': entry['reference']}
                for entry in release['workspace'].get('execution_manifest', {}).get('contracts', {}).values()}
        for prop in projection['properties'].values():
            prop.pop('execution_capabilities', None)
            if prop['id'] in execution_caps:
                prop['execution_capabilities'] = execution_caps[prop['id']]
                if workspace and not workspace.get('validation') and prop['execution_capabilities']['origin'] != 'builtin':
                    prop['execution_capabilities']['validation']['state'] = 'pending'
        knowledge = self.knowledge.load(knowledge_ref) if self.knowledge and knowledge_ref else None
        compatibility = knowledge_compatibility(knowledge, projection)
        for p in projection['properties'].values():
            links = compatibility['links'].get(p['id'], [])
            p['knowledge_links'] = links
            p['knowledge_coverage'] = {'available': sum(l['compatibility'] == 'compatible' for l in links), 'missing': int(not links)}
        if len(self._view_cache) >= 4:
            self._view_cache.pop(next(iter(self._view_cache)))
        self._view_cache[cache_key] = (projection, compatibility)
        return projection, workspace, bundle, revision, release, compatibility

    @staticmethod
    def _filtered(projection, kind, **filters):
        keyword = str(filters.get('keyword') or '').strip().casefold()
        type_id, family_id = filters.get('type_id'), filters.get('family_id')
        properties = projection['properties']; bindings = projection['bindings']
        property_ids = {b['property_key'] for b in bindings.values() if not type_id or b['type_id'] == type_id}
        result = []
        for item in projection[kind].values():
            if type_id and ((kind == 'types' and item['id'] != type_id) or (kind == 'properties' and item['id'] not in property_ids) or (kind == 'bindings' and item['type_id'] != type_id)):
                continue
            family = item.get('family_id') if kind == 'properties' else properties.get(item.get('property_key'), {}).get('family_id')
            if family_id and kind != 'types' and family != family_id:
                continue
            if family_id and kind == 'types' and not any(b['type_id'] == item['id'] and properties[b['property_key']]['family_id'] == family_id for b in bindings.values()):
                continue
            if filters.get('origin') not in (None, '', 'all', item['origin']):
                continue
            if filters.get('status') not in (None, '', 'all', item['status']):
                continue
            if keyword and keyword not in ' '.join(str(item.get(k, '')) for k in ('id', 'property_id', 'code', 'label', 'description', 'aliases')).casefold():
                continue
            result.append(item)
        sort = filters.get('sort', 'label')
        result.sort(key=lambda i: (str(i.get({'name': 'label', 'updated': 'revision'}.get(sort, sort), i.get('label', i['id']))).casefold(), i['id']))
        return result

    def list_items(self, kind, *, workspace_id=None, release_id=None, offset=0, limit=50, **filters):
        if kind not in KINDS:
            raise DomainError('INVALID_KIND', '未知规范对象类型', 422)
        projection, _, _, revision, _, _ = self._view(workspace_id, release_id)
        rows = self._filtered(projection, kind, **filters)
        offset = max(0, int(offset)); limit = min(100, max(1, int(limit)))
        return {'items': [self._public(r) for r in rows[offset:offset+limit]], 'total': len(rows), 'offset': offset, 'limit': limit, 'revision': revision}

    @staticmethod
    def _public(item):
        return {k: deepcopy(v) for k, v in item.items() if k != 'source_binding' and not k.startswith('_')}

    def detail(self, kind, item_id, **view):
        projection, _, _, _, _, _ = self._view(view.get('workspace_id'), view.get('release_id'))
        item = projection.get(kind, {}).get(item_id)
        if not item:
            raise DomainError('REGISTRY_ITEM_NOT_FOUND', '规范对象不存在', 404)
        result = self._public(item)
        result['dependents'] = self._dependents(projection, kind, item_id)
        result['bindings'] = [self._public(b) for b in projection['bindings'].values() if b.get('type_id' if kind == 'types' else 'property_key') == item_id]
        result['impact'] = {'dependents': result['dependents'], 'binding_count': len(result['bindings'])}
        return result

    @staticmethod
    def _dependents(projection, kind, item_id):
        dependents = []
        if kind == 'types':
            dependents.extend({'kind': 'types', 'id': t['id'], 'label': t['label']} for t in projection['types'].values() if t['parent_id'] == item_id and t['status'] == 'active')
        if kind in {'types', 'properties'}:
            field = 'type_id' if kind == 'types' else 'property_key'
            dependents.extend({'kind': 'bindings', 'id': b['id'], 'type_id': b['type_id'], 'property_key': b['property_key']} for b in projection['bindings'].values() if b[field] == item_id and b['status'] == 'active')
        return dependents

    def impact(self, workspace_id, kind, item_id):
        return self.detail(kind, item_id, workspace_id=workspace_id)['impact']

    def _capabilities(self, release):
        base = release.get('base_release', release)
        data = base.get('candidate', {}).get('data', base['data'])
        def values(role, identity):
            return [{'id': x[identity], 'label': x.get('name_cn', x.get('label', x.get('description', x[identity])))} for x in data.get(role, data.get(role.replace('_', '-'), []))]
        from .user_execution import local_conversion_policy
        local_policy = local_conversion_policy()
        conversion_policies = deepcopy(data.get('conversion_policies', data.get('conversion-policies', [])))
        conversion_policies = [local_policy, *[p for p in conversion_policies if p['policy_id'] != local_policy['policy_id']]]
        return {'user_execution_protocol': 'user-property-execution/1', 'subjects': values('subject_classes', 'subject_class_id'), 'scales': values('object_scales', 'object_scale_id'),
                'conversion_policies': conversion_policies}

    def summary(self, *, workspace_id=None, release_id=None, projection='full', **filters):
        if projection not in {'full', 'stats', 'directory'}:
            raise DomainError('INVALID_PROJECTION', '未知读取投影', 422)
        effective, workspace, bundle, revision, release, compatibility = self._view(workspace_id, release_id)
        scoped = {kind: self._filtered(effective, kind, **filters) for kind in KINDS}
        # Counts and facets are derived from the same effective scope as list rows.
        result = {'revision': revision, 'view': 'draft' if workspace else 'published', 'workspace': workspace and {k: workspace[k] for k in ('id', 'revision', 'status', 'base_bundle')},
                'active_bundle': bundle, 'counts': {**{k: len(v) for k, v in scoped.items()},
                'disabled': sum(i['status'] == 'disabled' for rows in scoped.values() for i in rows),
                'changed': sum(i['origin'] != 'builtin' for rows in scoped.values() for i in rows)},
                'knowledge_coverage': {'available': sum(any(l['compatibility'] == 'compatible' for l in p.get('knowledge_links', [])) for p in scoped['properties']), 'missing': sum(not any(l['compatibility'] == 'compatible' for l in p.get('knowledge_links', [])) for p in scoped['properties'])},
                'workspace_available': True}
        if projection != 'stats':
            directory = {kind: self._filtered(effective, kind) for kind in ('types', 'properties')} if projection == 'directory' else scoped
            family_counts = {}
            for p in directory['properties']:
                family_counts[p['family_id']] = family_counts.get(p['family_id'], 0) + 1
            families = {f['family_id']: f for f in release['data'].get('families', [])}
            result['types'] = [self._public(t) for t in directory['types']]
            result['families'] = [{'id': f, 'label': families.get(f, {}).get('name_cn') or families.get(f, {}).get('label') or families.get(f, {}).get('name') or next((p['label'] for p in directory['properties'] if p['family_id'] == f), f), 'description': families.get(f, {}).get('description', ''), 'count': count} for f, count in sorted(family_counts.items())]
        if projection == 'full':
            result['capabilities'] = self._capabilities(release)
        return result

    def graph(self, *, workspace_id=None, release_id=None, view='overview', focus_id=None, limit=80, **filters):
        projection, _, _, revision, _, _ = self._view(workspace_id, release_id)
        if view not in {'overview', 'type', 'property'} or limit not in (80, 120, 200):
            raise DomainError('INVALID_GRAPH', '图谱视图或预算无效', 422)
        if view == 'type':
            filters['type_id'] = focus_id
        properties = self._filtered(projection, 'properties', **filters)
        if view == 'property':
            properties = [p for p in properties if p['id'] == focus_id]
        pids = {p['id'] for p in properties}
        bindings = [b for b in projection['bindings'].values() if b['property_key'] in pids and b['status'] == 'active' and (not filters.get('type_id') or b['type_id'] == filters['type_id'])]
        tids = {b['type_id'] for b in bindings}
        adjacent_types = [t for t in self._filtered(projection, 'types', **{k: v for k, v in filters.items() if k != 'keyword'}) if t['id'] in tids]
        if view == 'property':
            types = adjacent_types
        else:
            type_filters = {k: v for k, v in filters.items() if k not in {'keyword', 'family_id'}} if view == 'type' else filters
            matched_types = self._filtered(projection, 'types', **type_filters)
            # A type is a real registry record even before its first binding.
            # Search retains direct type matches; property matches add only
            # their actual adjacent types and never imply applicability edges.
            types = list({t['id']: t for t in [*matched_types, *adjacent_types]}.values())
        all_items = [*types, *properties]
        # Reserve room for both ends of applicability edges at every budget.
        real_budget = limit - 2 if len(all_items) > limit else limit
        type_budget = min(len(types), max(1, real_budget // 3)) if properties else real_budget
        selected_types = types[:type_budget]
        adjacent = {b['property_key'] for b in bindings if b['type_id'] in {t['id'] for t in selected_types}}
        ordered_properties = sorted(properties, key=lambda p: p['id'] not in adjacent)
        selected = [*selected_types, *ordered_properties[:real_budget-type_budget]]
        if len(selected) < real_budget:
            selected += types[type_budget:type_budget+real_budget-len(selected)]
        shown = {i['id'] for i in selected}
        nodes = [{'id': i['kind'] + ':' + i['id'], 'record_id': i['id'], 'kind': i['kind'], 'source_kind': i['kind'], 'label': i['label'], 'category': i.get('family_id', 'types'), 'origin': i['origin'], 'status': i['status'], **({'code': i['code'], 'property_count': i['property_count'], 'count': i['property_count']} if i['kind'] == 'type' else {}), **({'color': i['color']} if i.get('color') else {})} for i in selected]
        edges = [{'id': b['id'], 'source': 'type:' + b['type_id'], 'target': 'property:' + b['property_key'],
                  'relation_type': 'conditional' if b['conditional'] else 'applicable'} for b in bindings if b['type_id'] in shown and b['property_key'] in shown]
        edges += [{'id': 'parent:' + t['id'], 'source': 'type:' + t['parent_id'], 'target': 'type:' + t['id'], 'relation_type': 'hierarchy'} for t in types if t['id'] in shown and t['parent_id'] in shown]
        for kind, items in (('type', types), ('property', properties)):
            omitted = [i['id'] for i in items if i['id'] not in shown]
            if omitted:
                nodes.append({'id': 'aggregate:' + kind, 'kind': 'aggregate', 'source_kind': kind,
                    'label': f'其余 {len(omitted)} 个' + ('类型' if kind == 'type' else '性质'),
                    'count': len(omitted), 'member_ids': omitted, 'category': 'overflow',
                    'filters': {k: v for k, v in filters.items() if v is not None}})
        aggregated_edges = {}
        for binding in bindings:
            if binding['type_id'] in shown and binding['property_key'] in shown:
                continue
            source = 'type:' + binding['type_id'] if binding['type_id'] in shown else 'aggregate:type'
            target = 'property:' + binding['property_key'] if binding['property_key'] in shown else 'aggregate:property'
            relation = 'conditional' if binding['conditional'] else 'applicable'
            edge_key = (source, target, relation)
            aggregated_edges[edge_key] = aggregated_edges.get(edge_key, 0) + 1
        node_ids = {n['id'] for n in nodes}
        edges.extend({'id': 'aggregate-edge:' + digest([source, target, relation]), 'source': source,
            'target': target, 'relation_type': relation, 'aggregate': True, 'count': count}
            for (source, target, relation), count in aggregated_edges.items() if source in node_ids and target in node_ids)
        return {'nodes': nodes, 'edges': edges, 'categories': [{'id': f, 'label': f} for f in sorted({n['category'] for n in nodes})],
            'meta': {'total_types': len(types), 'total_properties': len(properties), 'matched_entries': len(all_items),
                     'shown_entries': len(selected), 'node_count': len(nodes), 'truncated': len(all_items) > len(selected),
                     'view': view, 'focus_id': (view + ':' + focus_id) if view in {'type', 'property'} and focus_id else None, 'revision': revision, 'represented_entries': len(all_items)}}

    @persistence_errors
    def write(self, workspace_id, kind, payload, *, item_id=None, expected_revision=None):
        if kind not in KINDS or not isinstance(payload, dict):
            raise DomainError('INVALID_REGISTRY_WRITE', '规范编辑对象无效', 422)
        with self.repository.transaction() as conn:
            workspace = self._workspace(conn, workspace_id); self._revision(workspace, expected_revision)
            release, base = self._base(workspace['base_bundle']['registry_ref'])
            projection = apply_operations(base, workspace['operations'])
            old = projection[kind].get(item_id) if item_id else None
            if item_id and not old:
                raise DomainError('REGISTRY_ITEM_NOT_FOUND', '规范对象不存在', 404)
            item = self._prepare(kind, payload, old, projection, release)
            if item['status'] == 'disabled':
                dependents = self._dependents(projection, kind, item['id'])
                if dependents:
                    raise DomainError('REGISTRY_DEPENDENTS', '仍有引用，请先逐项处理依赖', 409, dependents=dependents)
            operations = [{'kind': kind, 'id': item['id'], 'action': 'put', 'item': item}]
            projection[kind][item['id']] = item
            if kind == 'properties' and not old:
                for type_id in payload.get('type_ids', []):
                    binding = self._prepare('bindings', {'type_id': type_id, 'property_key': item['id']}, None, projection, release)
                    operations.append({'kind': 'bindings', 'id': binding['id'], 'action': 'put', 'item': binding})
            # A shared definition edit updates exact refs on every binding, and
            # suspends prior scope permissions rather than copying approval.
            if kind == 'properties' and old and item['definition_ref'] != old['definition_ref']:
                for b in projection['bindings'].values():
                    if b['property_key'] != item['id']:
                        continue
                    changed = deepcopy(b); changed['definition_ref'] = item['definition_ref']
                    new_reference = item.get('_profile_changes', {}).get(key(b['profile_ref']), b['profile_ref'])
                    profile = next((p for p in item['output_profiles'] if ref(p, 'profile') == new_reference), None)
                    if b.get('output_profile'):
                        profile = deepcopy(b['output_profile'])
                        profile['definition_version'] = item['definition']['definition_version']
                        profile['version'] += 1
                        profile['content_sha256'] = content_hash(profile)
                        changed['output_profile'] = profile
                    if profile is None:
                        raise DomainError('REGISTRY_DEPENDENTS', '共享定义仍有输出配置依赖', 409)
                    changed['profile_ref'] = ref(profile, 'profile')
                    changed.update(origin='override' if b['origin'] == 'builtin' else b['origin'], revision=b['revision'] + 1, automatic_execution_ready=False)
                    operations.append({'kind': 'bindings', 'id': b['id'], 'action': 'put', 'item': changed})
            elif kind == 'properties' and old and item['output_profiles'] != old['output_profiles']:
                for b in projection['bindings'].values():
                    if b['property_key'] != item['id']:
                        continue
                    if b.get('output_profile'):
                        continue
                    new_reference = item.get('_profile_changes', {}).get(key(b['profile_ref']), b['profile_ref'])
                    profile = next((p for p in item['output_profiles'] if ref(p, 'profile') == new_reference), None)
                    if profile is None:
                        raise DomainError('REGISTRY_DEPENDENTS', '仍被绑定的输出配置不可删除', 409)
                    if ref(profile, 'profile') == b['profile_ref']:
                        continue
                    changed = deepcopy(b); changed.update(profile_ref=ref(profile, 'profile'), automatic_execution_ready=False, revision=b['revision'] + 1, origin='override')
                    operations.append({'kind': 'bindings', 'id': b['id'], 'action': 'put', 'item': changed})
            workspace['operations'].extend(operations); workspace['revision'] += 1; workspace['validation'] = None
            self._save(conn, workspace)
        return {'success': True, 'workspace': {k: workspace[k] for k in ('id', 'revision', 'status')}, 'item': self._public(item)}

    def _prepare(self, kind, payload, old, projection, release):
        common = {'id': old['id'] if old else ('user_type_' if kind == 'types' else 'property_' if kind == 'properties' else 'binding_') + new_id(),
            'kind': kind[:-1] if kind != 'properties' else 'property', 'origin': ('override' if old['origin'] == 'builtin' else old['origin']) if old else 'user',
            'status': payload.get('status', old['status'] if old else 'active'), 'revision': old['revision'] + 1 if old else 1}
        if common['status'] not in {'active', 'disabled'}:
            raise DomainError('INVALID_STATUS', '规范状态无效', 422)
        item = deepcopy(old or {}); item.update(common)
        allowed_common = {'label', 'description', 'aliases', 'source_note', 'notes', 'status'}
        allowed = allowed_common | ({'parent_id', 'conditions', 'excluded_conditions', 'color', 'code', 'standard_otype'} if kind == 'types' else
            {'definition', 'output_profiles', 'family_id', 'type_ids', 'execution_examples'} if kind == 'properties' else
            {'type_id', 'property_key', 'profile_ref', 'conditions', 'excluded_conditions', 'display_order', 'output_profile'})
        extra = set(payload) - allowed - {'expected_revision'}
        if extra:
            raise DomainError('INVALID_REGISTRY_FIELDS', '规范编辑包含不可写字段', 422, fields=sorted(extra))
        item.update({k: deepcopy(v) for k, v in payload.items() if k in allowed_common})
        if kind != 'bindings' and not str(item.get('label', '')).strip():
            raise DomainError('INVALID_LABEL', '名称不能为空', 422)
        if kind == 'types':
            if old and old['id'] == old.get('standard_otype') and any(k in payload and payload[k] != old.get(k) for k in ('code', 'parent_id', 'standard_otype')):
                raise DomainError('STANDARD_TYPE_IMMUTABLE', '官方类型标识及来源层级不可修改', 422)
            item.setdefault('code', item['id']); item.setdefault('description', ''); item.setdefault('aliases', [])
            item.setdefault('source_refs', []); item.setdefault('conditions', []); item.setdefault('property_count', 0)
            for field in ('parent_id', 'conditions', 'excluded_conditions', 'color', 'code'):
                if field in payload:
                    item[field] = deepcopy(payload[field])
            if old and item.get('parent_id') != old.get('parent_id'):
                descendants = [t['id'] for t in projection['types'].values() if t.get('parent_id') == old['id']]
                if descendants:
                    raise DomainError('REGISTRY_DEPENDENTS', '父类型仍有子类型，不能静默重定锚点', 409, dependents=descendants)
            if not old or old['id'] != old.get('standard_otype'):
                parent_id = item.get('parent_id')
                seen = {item['id']}; parent = projection['types'].get(parent_id)
                while parent and parent['id'] != parent.get('standard_otype'):
                    if parent['status'] != 'active':
                        raise DomainError('TYPE_PARENT_REQUIRED', '父链包含已禁用类型', 422)
                    if parent['id'] in seen:
                        raise DomainError('TYPE_CYCLE', '自定义类型父链存在循环', 422)
                    seen.add(parent['id']); parent = projection['types'].get(parent.get('parent_id'))
                if not parent or parent['status'] != 'active':
                    raise DomainError('TYPE_PARENT_REQUIRED', '自定义类型必须有唯一有效官方锚点', 422)
                item['standard_otype'] = parent['standard_otype']
            if item.get('color'):
                import re
                if not isinstance(item['color'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', item['color']):
                    raise DomainError('INVALID_TYPE_COLOR', '分类颜色必须为六位十六进制色值', 422)
            elif 'color' in item:
                item.pop('color')
            if not isinstance(item['code'], str) or not item['code'].strip() or len(item['code']) > 128:
                raise DomainError('INVALID_TYPE_CODE', '类型编码不能为空或超过128字符', 422)
            if any(t['id'] != item['id'] and t['code'] == item['code'] for t in projection['types'].values()):
                raise DomainError('DUPLICATE_TYPE_CODE', '类型编码已存在', 422)
            item['content_sha256'] = content_hash(item)
        elif kind == 'properties':
            definition = deepcopy(old['definition'] if old else {})
            definition.update(deepcopy(payload.get('definition', {})))
            from .models import PropertyDefinition, OutputProfile
            unknown = set(definition) - set(PropertyDefinition.model_fields)
            if unknown:
                raise DomainError('INVALID_DEFINITION_FIELDS', '定义包含未知或不可执行字段', 422, fields=sorted(unknown))
            if old and any(definition.get(k) != old['definition'].get(k) for k in IDENTITY):
                raise DomainError('SCIENTIFIC_IDENTITY_IMMUTABLE', '科学身份变化必须新建性质', 422)
            pid = old['property_id'] if old else 'user_property_' + new_id()
            definition['property_id'] = pid
            defaults = {'property_id': pid, 'definition_version': 1, 'name_cn': item['label'], 'name_en': None,
                'aliases': item.get('aliases', []), 'description': item.get('description', item['label']),
                'quantity_key': 'user:' + pid, 'quantity_kind': 'user_declared', 'scientific_purpose': '用户来源定义',
                'scope': 'whole_object', 'definition_qualifiers': {}, 'measurement_conditions_schema': [],
                'value_schema': {'kind': 'real'}, 'distinction_notes': [], 'ucd': {}, 'evidence_refs': []}
            for k, v in defaults.items():
                definition.setdefault(k, v)
            if 'family_id' in payload:
                definition['family_id'] = payload['family_id']
            if not definition.get('family_id') or not definition.get('subject_class_id'):
                raise DomainError('PROPERTY_CONTEXT_REQUIRED', '必须指定性质族与科学主体', 422)
            semantic_changed = not old or any(definition.get(k) != old['definition'].get(k) for k in definition if k not in {'content_sha256', 'definition_version'})
            if semantic_changed:
                definition['definition_version'] = old['definition']['definition_version'] + 1 if old else 1
                # Previous review belongs to previous semantics; retain it only
                # as source metadata, never as an approval of user edits.
                item['source_review_ref'] = definition.pop('review_ref', None)
                definition['content_sha256'] = content_hash(definition)
            if old and not semantic_changed:
                definition = deepcopy(old['definition'])
            output_profiles = deepcopy(payload.get('output_profiles', old['output_profiles'] if old else []))
            item['_profile_changes'] = {}
            for index, profile in enumerate(output_profiles):
                unknown = set(profile) - set(OutputProfile.model_fields)
                if unknown:
                    raise DomainError('INVALID_PROFILE_FIELDS', '输出配置包含未知字段', 422, fields=sorted(unknown))
                if not old:
                    profile['profile_id'] = 'user_profile_' + new_id()
                prior = next((p for p in old['output_profiles'] if p['profile_id'] == profile.get('profile_id')
                    and p['version'] == profile.get('version') and p['content_sha256'] == profile.get('content_sha256')), None) if old else None
                if prior is None and old and index < len(old['output_profiles']) and old['output_profiles'][index]['profile_id'] == profile.get('profile_id'):
                    # A caller cannot choose hashes/versions; an unchanged slot
                    # still resolves its original exact source record.
                    prior = old['output_profiles'][index]
                profile.setdefault('profile_id', 'user_profile_' + new_id()); profile.setdefault('version', 1)
                profile.update(property_id=pid, definition_version=definition['definition_version'])
                changed = not prior or any(profile.get(k) != prior.get(k) for k in set(profile) | set(prior or {}) if k not in {'content_sha256', 'version'})
                if changed:
                    profile['version'] = prior['version'] + 1 if prior else 1
                    profile.pop('review_ref', None)
                    profile['content_sha256'] = content_hash(profile)
                if prior and not changed:
                    profile.update(version=prior['version'], content_sha256=prior['content_sha256'])
                if prior:
                    item['_profile_changes'][key(ref(prior, 'profile'))] = ref(profile, 'profile')
                if prior and prior.get('unit', {}).get('kind') == 'physical' and profile.get('unit', {}).get('kind') == 'physical':
                    item.setdefault('original_unit', deepcopy(prior['unit']))
            item.update(property_id=pid, definition=definition, definition_ref=ref(definition), output_profiles=output_profiles,
                family_id=definition['family_id'], source_refs=deepcopy(old.get('source_refs', []) if old else []),
                definition_unchanged=bool(old and old.get('definition_unchanged', True) and not semantic_changed),
                automatic_conversion_ready=bool(old and old.get('automatic_conversion_ready') and not semantic_changed and output_profiles == old['output_profiles']))
            examples = deepcopy(payload.get('execution_examples', old.get('execution_examples', []) if old else []))
            if not isinstance(examples, list) or len(examples) > 20 or any(not isinstance(e, dict) for e in examples):
                raise DomainError('INVALID_EXECUTION_EXAMPLES', 'Examples must be an array of at most 20 objects', 422)
            for example in examples:
                required = {'label', 'source_value', 'source_unit', 'source_representation', 'expected_value'}
                if not required <= example.keys() or set(example) - required - {'profile_ref'} or not all(isinstance(example[k], str) and len(example[k]) <= 4096 for k in ('label', 'source_value', 'source_unit', 'expected_value')):
                    raise DomainError('INVALID_EXECUTION_EXAMPLES', 'Expected numeric example fields only; no formulas or scripts', 422)
                if example.get('profile_ref'):
                    from astroquery_ai.runtime.models import Ref
                    try:
                        Ref.model_validate(example['profile_ref'])
                    except ValueError as exc:
                        raise DomainError('INVALID_EXECUTION_EXAMPLES', '样例输出配置必须提供完整精确引用', 422) from exc
                    example['profile_ref'] = item['_profile_changes'].get(key(example['profile_ref']), example['profile_ref'])
            item['execution_examples'] = examples
            item.setdefault('description', definition['description']); item.setdefault('aliases', definition['aliases'])
        else:
            for k in ('type_id', 'property_key', 'profile_ref', 'conditions', 'excluded_conditions', 'display_order'):
                if k in payload:
                    item[k] = deepcopy(payload[k])
            prop = projection['properties'].get(item.get('property_key')); target = projection['types'].get(item.get('type_id'))
            if not prop or not target or prop['status'] != 'active' or target['status'] != 'active':
                raise DomainError('INVALID_BINDING_DEPENDENCY', '绑定必须引用有效类型和精确性质记录', 422)
            item.setdefault('conditions', []); item.setdefault('excluded_conditions', []); item.setdefault('display_order', 0)
            item.setdefault('rule_refs', []); item['definition_ref'] = prop['definition_ref']
            if 'output_profile' in payload and payload['output_profile'] is None:
                item.pop('output_profile', None)
            if payload.get('output_profile') is not None:
                profile = deepcopy(payload['output_profile']); profile.update(profile_id='user_profile_' + new_id(), version=1,
                    property_id=prop['property_id'], definition_version=prop['definition']['definition_version'])
                profile.pop('review_ref', None); profile['content_sha256'] = content_hash(profile)
                item['output_profile'] = profile; item['profile_ref'] = ref(profile, 'profile')
            if not item.get('profile_ref'):
                if not prop['output_profiles']:
                    raise DomainError('OUTPUT_PROFILE_REQUIRED', '性质缺少输出配置', 422)
                item['profile_ref'] = ref(prop['output_profiles'][0], 'profile')
            if not item.get('output_profile') and not any(ref(p, 'profile') == item['profile_ref'] for p in prop['output_profiles']):
                raise DomainError('INVALID_PROFILE_REF', '输出配置引用不匹配', 422)
            if any(b['id'] != item['id'] and b['type_id'] == item['type_id'] and b['property_key'] == item['property_key'] and b['profile_ref'] == item['profile_ref'] and b['status'] == 'active' for b in projection['bindings'].values()):
                raise DomainError('DUPLICATE_BINDING', '此类型已包含同一精确性质配置', 409)
            changed = not old or any(item.get(k) != old.get(k) for k in ('type_id', 'property_key', 'profile_ref', 'conditions', 'excluded_conditions'))
            item['automatic_execution_ready'] = bool(old and old.get('automatic_execution_ready', True) and not changed)
            if old and old.get('source_binding') and not item['automatic_execution_ready']:
                from .workspace_release import original_release
                _, original = self._base(release_ref(original_release(release)))
                source = original['bindings'].get(item['id'])
                # Restoring the exact original scope may reuse its existing
                # qualification; approximate names or changed science cannot.
                item['automatic_execution_ready'] = bool(source and all(item.get(field) == source.get(field)
                    for field in ('type_id', 'property_key', 'definition_ref', 'profile_ref', 'output_profile', 'conditions', 'excluded_conditions')))
            item['conditional'] = bool(item['conditions'])
        from .compiler import condition_variables
        for condition in item.get('conditions', []) + item.get('excluded_conditions', []):
            condition_variables(condition)
        return item

    @persistence_errors
    def delete(self, workspace_id, kind, item_id, *, expected_revision=None):
        with self.repository.transaction() as conn:
            workspace = self._workspace(conn, workspace_id); self._revision(workspace, expected_revision)
            _, base = self._base(workspace['base_bundle']['registry_ref'])
            projection = apply_operations(base, workspace['operations']); item = projection.get(kind, {}).get(item_id)
            if not item:
                raise DomainError('REGISTRY_ITEM_NOT_FOUND', '规范对象不存在', 404)
            dependents = self._dependents(projection, kind, item_id)
            if dependents:
                raise DomainError('REGISTRY_DEPENDENTS', '仍有引用，请先处理依赖', 409, dependents=dependents)
            if item_id not in base[kind]:
                operation = {'kind': kind, 'id': item_id, 'action': 'remove'}
            else:
                item = {**item, 'status': 'disabled', 'revision': item['revision'] + 1, 'origin': 'override' if item['origin'] == 'builtin' else item['origin']}
                operation = {'kind': kind, 'id': item_id, 'action': 'put', 'item': item}
            workspace['operations'].append(operation); workspace['revision'] += 1; workspace['validation'] = None
            self._save(conn, workspace)
        return {'success': True, 'workspace': {k: workspace[k] for k in ('id', 'revision', 'status')}}

    @persistence_errors
    def validate(self, workspace_id, *, expected_revision=None):
        from .workbench_validation import validate_projection
        with self.repository.transaction() as conn:
            workspace = self._workspace(conn, workspace_id); self._revision(workspace, expected_revision)
            release, base = self._base(workspace['base_bundle']['registry_ref'])
            projection = apply_operations(base, workspace['operations'])
            errors, warnings = validate_projection(projection, self._capabilities(release))
            from .user_execution import compile_execution
            execution, execution_caps, execution_errors = compile_execution(projection, release)
            errors.extend(execution_errors)
            knowledge_ref = workspace['base_bundle'].get('knowledge_ref')
            knowledge = self.knowledge.load(knowledge_ref) if self.knowledge and knowledge_ref else None
            compatibility = knowledge_compatibility(knowledge, projection)
            validation = {'id': 'validation_' + new_id(), 'workspace_revision': workspace['revision'],
                'state': 'failed' if errors else 'passed', 'errors': errors, 'warnings': warnings,
                'impact': {'changed': len({(op['kind'], op['id']) for op in workspace['operations']}), 'new_tasks_only': True},
                'knowledge_coverage': {k: compatibility[k] for k in ('available', 'missing')},
                'capabilities': {'automatic_unavailable': [p['id'] for p in projection['properties'].values() if not p.get('automatic_conversion_ready')],
                                 'review_granted': False, 'qualification_granted': False},
                'execution': {'manifest': execution, 'properties': execution_caps},
                'projection_sha256': digest(projection)}
            workspace['validation'] = validation; self._save(conn, workspace)
        return {'success': not errors, 'validation': validation}

    def publish(self, workspace_id, *, expected_revision, validation_id, expected_active_bundle_id, idempotency_key):
        from .workbench_publication import publish
        return publish(self, workspace_id, expected_revision=expected_revision, validation_id=validation_id,
                       expected_active_bundle_id=expected_active_bundle_id, idempotency_key=idempotency_key)

    def activate(self, release_id, *, expected_active_bundle_id, idempotency_key):
        from .workbench_publication import activate
        return activate(self, release_id, expected_active_bundle_id=expected_active_bundle_id, idempotency_key=idempotency_key)

    def list_releases(self, *, projection='full'):
        if projection not in {'full', 'directory'}:
            raise DomainError('INVALID_PROJECTION', '未知读取投影', 422)
        with self.repository.read() as conn:
            bundles = [loads(row[0]) for row in conn.execute('SELECT payload FROM registry_bundles ORDER BY created_at DESC')]
        active = self.registry.active_bundle()
        if not any(b['id'] == active['id'] for b in bundles):
            bundles.insert(0, active)
        items = [self._directory_item(b) if projection == 'directory' else b for b in bundles]
        return {'items': [{**b, 'release_id': b['registry_ref']['id'], 'active': b['id'] == active['id']} for b in items], 'total': len(items)}


    def knowledge_detail(self, entry_id, *, workspace_id=None, release_id=None):
        projection, workspace, bundle, revision, release, compatibility = self._view(workspace_id, release_id)
        reference = workspace['base_bundle'].get('knowledge_ref') if workspace else release.get('workspace', {}).get('base_knowledge_ref', bundle.get('knowledge_ref'))
        if not self.knowledge or not reference:
            raise DomainError('KNOWLEDGE_ENTRY_NOT_FOUND', '此发布缺少对应作者知识卡', 404)
        knowledge = self.knowledge.load(reference)
        entry = knowledge.get('entries', {}).get(entry_id)
        if not entry:
            raise DomainError('KNOWLEDGE_ENTRY_NOT_FOUND', '此发布不存在对应作者知识卡', 404)
        source_ids = {sid for block in entry.get('blocks', []) for sid in block.get('source_ids', [])}
        sources = [deepcopy(source) for sid, source in knowledge.get('sources', {}).items() if sid in source_ids]
        links = [{'property_key': p, **link} for p, values in compatibility['links'].items() for link in values if link['entry_id'] == entry_id]
        return {'entry': deepcopy(entry), 'sources': sources, 'compatibility': links, 'read_only': True, 'revision': revision}
