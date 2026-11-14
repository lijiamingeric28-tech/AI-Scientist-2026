"""Transactional user overlay and shared query implementation for the workbench."""
from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy

from astroquery_ai.runtime.errors import DomainError
from .knowledge_categories import KnowledgeCategoriesMixin
from .knowledge_projection import (category_facets, entry_properties, entry_source,
    entry_summary, graph_projection, property_key)

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


class OverlayLock:
    """Reentrant thread lock backed by one OS file lock for the entire transaction."""
    def __init__(self, path):
        self.path = path.parent / '.user_knowledge.lock'
        self.mutex = threading.RLock()
        self.local = threading.local()

    @property
    def depth(self):
        return getattr(self.local, 'depth', 0)

    def __enter__(self):
        self.mutex.acquire()
        try:
            if self.depth == 0:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                stream = self.path.open('a+b')
                try:
                    stream.seek(0, 2)
                    if stream.tell() == 0:
                        stream.write(b'0')
                        stream.flush()
                    stream.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                except BaseException:
                    stream.close()
                    raise
                self.local.stream = stream
            self.local.depth = self.depth + 1
            return self
        except BaseException as exc:
            self.mutex.release()
            if isinstance(exc, OSError):
                raise DomainError('KNOWLEDGE_LOCK_FAILED', '用户知识文件暂时无法锁定', 503) from exc
            raise

    def __exit__(self, *_):
        try:
            self.local.depth -= 1
            if self.depth == 0:
                stream = self.local.stream
                try:
                    stream.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                finally:
                    stream.close()
                    del self.local.stream
        finally:
            self.mutex.release()


def overlay_lock(path):
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(os.path.normcase(str(path.resolve())), OverlayLock(path))


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _invalid(message):
    raise DomainError('KNOWLEDGE_INVALID_INPUT', message, 422)


class KnowledgeWorkbenchMixin(KnowledgeCategoriesMixin):
    @contextmanager
    def _locked(self):
        with self._lock:
            if self._lock.depth == 1:
                self._refresh_overlay()
            yield

    def _disk_signature(self):
        try:
            status = self.overlay_file.stat()
            return (status.st_mtime_ns, status.st_size, status.st_ino)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise DomainError('KNOWLEDGE_OVERLAY_UNAVAILABLE', '用户知识文件无法读取', 503) from exc

    def _refresh_overlay(self):
        if self._disk_signature() != self._overlay_signature:
            self._load_user_overlay()

    def _base_entry(self, entry_id):
        from .user_knowledge_store import COMMON_ALIASES
        eid = str(entry_id or '').strip()
        candidates = [eid, COMMON_ALIASES.get(eid.lower(), ''),
                      *[prefix + eid for prefix in ('type_profile:', 'research_entry:', 'author:', 'law.')]]
        for candidate in candidates:
            if candidate in self.base_entries_by_id:
                return self.base_entries_by_id[candidate]
        for key, entry in self.base_entries_by_id.items():
            if key.casefold() == eid.casefold():
                return entry
        return None

    def _canonical_id(self, entry_id):
        eid = str(entry_id or '').strip()
        if eid in self.user_entries:
            return eid
        item = self._base_entry(eid)
        return item['id'] if item else eid

    def _load_user_overlay(self):
        seeds = {'stefan_boltzmann_law': {'preference': 'preferred', 'weight_boost': 2.0},
                 'eddington_luminosity_limit': {'preference': 'preferred', 'weight_boost': 2.0},
                 'chandrasekhar_mass_limit': {'preference': 'preferred', 'weight_boost': 2.0},
                 'gaia_astrometric_parallax': {'preference': 'preferred', 'weight_boost': 1.8}}
        if not self.overlay_file.exists():
            self.user_entries = {}
            self.user_overrides = {}
            self.preferences = {self._canonical_id(key): value for key, value in seeds.items()}
            self.cleared_preferences = set()
            self.deleted_ids = set()
            self.revision = 0
            self.entry_revisions = {}
            self.custom_categories = {}
            self.deleted_category_ids = set()
            self.category_redirects = {}
            self.category_appearance = {}
            self.category_order = []
            self._overlay_signature = None
            return
        try:
            raw = json.loads(self.overlay_file.read_text(encoding='utf-8'))
            if not isinstance(raw, dict):
                raise ValueError('overlay must be an object')
            for key in ('user_entries', 'overrides', 'preferences', 'entry_revisions', 'custom_categories',
                        'category_redirects', 'category_appearance'):
                if not isinstance(raw.get(key, {}), dict):
                    raise ValueError(key)
            revision = raw.get('revision', 0)
            revisions = raw.get('entry_revisions', {})
            if any(type(value) is not int or value < 0 for value in [revision, *revisions.values()]):
                raise ValueError('invalid revision')
            if any(not isinstance(value, dict) for key in ('user_entries', 'overrides', 'preferences')
                   for value in raw.get(key, {}).values()):
                raise ValueError('invalid overlay item')
            preferences = {self._canonical_id(key): value for key, value in seeds.items()}
            preferences.update({self._canonical_id(key): value for key, value in raw.get('preferences', {}).items()})
            cleared = {self._canonical_id(key) for key in raw.get('cleared_preferences', [])}
            for key in cleared:
                preferences.pop(key, None)
            deleted = {self._canonical_id(key) for key in raw.get('deleted_ids', [])}
            categories = raw.get('custom_categories', {})
            deleted_categories = raw.get('deleted_category_ids', [])
            redirects = raw.get('category_redirects', {})
            appearance = raw.get('category_appearance', {})
            order = raw.get('category_order', [])
            if (not isinstance(order, list) or any(not isinstance(key, str) for key in order)
                    or len(set(order)) != len(order)):
                raise ValueError('invalid category order')
            from .user_knowledge_store import KNOWLEDGE_CATEGORIES
            builtin_ids = {item['id'] for item in KNOWLEDGE_CATEGORIES}
            for key, item in appearance.items():
                if (key not in builtin_ids or not isinstance(item, dict)
                        or set(item) != {'color', 'revision'} or type(item['revision']) is not int
                        or item['revision'] < 0):
                    raise ValueError('invalid category appearance')
                try:
                    item['color'] = self._validate_category_color(item['color'])
                except DomainError as exc:
                    raise ValueError('invalid category color') from exc
            if not isinstance(deleted_categories, list) or any(not isinstance(key, str) for key in deleted_categories):
                raise ValueError('invalid deleted categories')
            if any(not isinstance(value, str) or not value.strip() or key not in deleted_categories
                   for key, value in redirects.items()):
                raise ValueError('invalid category migration')
            for key, item in categories.items():
                if (not isinstance(item, dict) or item.get('id') != key or not isinstance(item.get('label'), str)
                        or not item['label'].strip() or not isinstance(item.get('color'), str)
                        or item.get('is_custom') is not True or type(item.get('revision')) is not int
                        or item['revision'] < 0 or key in deleted_categories):
                    raise ValueError('invalid custom category')
            signature = self._disk_signature()
        except (OSError, ValueError, TypeError) as exc:
            # Never overwrite an unreadable existing overlay with an empty one.
            raise DomainError('KNOWLEDGE_OVERLAY_UNAVAILABLE', '用户知识文件无法读取', 503) from exc
        # Publish a complete validated read, never a partially loaded overlay.
        self.user_entries = raw.get('user_entries', {})
        self.user_overrides = raw.get('overrides', {})
        self.preferences = preferences
        self.cleared_preferences = cleared
        self.deleted_ids = deleted
        self.revision = revision
        self.entry_revisions = revisions
        self.custom_categories = categories
        self.deleted_category_ids = set(deleted_categories)
        self.category_redirects = redirects
        self.category_appearance = appearance
        self.category_order = order
        self._overlay_signature = signature

    def _state(self):
        return deepcopy({'user_entries': self.user_entries, 'overrides': self.user_overrides,
                         'preferences': self.preferences, 'deleted_ids': sorted(self.deleted_ids),
                         'cleared_preferences': sorted(self.cleared_preferences),
                         'revision': self.revision, 'entry_revisions': self.entry_revisions,
                         'custom_categories': self._custom_category_registry(),
                         'deleted_category_ids': sorted(self.deleted_category_ids),
                         'category_redirects': self.category_redirects,
                         'category_appearance': self.category_appearance,
                         'category_order': [item['id'] for item in self._category_definitions()]})

    def _save_user_overlay(self, payload):
        temporary = None
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.data_dir,
                                             prefix='user_knowledge.', suffix='.tmp', delete=False) as stream:
                temporary = stream.name
                json.dump({**payload, 'updated_at': _now()}, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.overlay_file)
        except (OSError, ValueError, TypeError) as exc:
            raise DomainError('KNOWLEDGE_SAVE_FAILED', '用户知识保存失败，草稿尚未写入', 503) from exc
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def _commit(self, payload, eid=None, *, affected_ids=()):
        payload['revision'] = self.revision + 1
        for affected in set(affected_ids) | ({eid} if eid is not None else set()):
            payload['entry_revisions'][affected] = self.entry_revisions.get(affected, 0) + 1
        payload['custom_categories'] = self._infer_categories(payload['custom_categories'],
            [*self.base_entries, *payload['user_entries'].values(), *payload['overrides'].values()],
            payload['deleted_category_ids'])
        payload['category_order'] = self._ordered_category_ids(payload['custom_categories'], payload['category_order'])
        self._save_user_overlay(payload)
        # Publish the candidate only after atomic replacement succeeded.
        self.user_entries = payload['user_entries']
        self.user_overrides = payload['overrides']
        self.preferences = payload['preferences']
        self.deleted_ids = set(payload['deleted_ids'])
        self.revision = payload['revision']
        self.entry_revisions = payload['entry_revisions']
        self.cleared_preferences = set(payload['cleared_preferences'])
        self.custom_categories = payload['custom_categories']
        self.deleted_category_ids = set(payload['deleted_category_ids'])
        self.category_redirects = payload['category_redirects']
        self.category_appearance = payload['category_appearance']
        self.category_order = payload['category_order']
        self._overlay_signature = self._disk_signature()

    def _expect(self, eid, expected_revision):
        if expected_revision is None:
            return
        if type(expected_revision) is not int or expected_revision < 0:
            _invalid('expected_revision须为非负整数')
        actual = self.entry_revisions.get(eid, 0)
        if expected_revision != actual:
            raise DomainError('KNOWLEDGE_REVISION_CONFLICT', '条目已被修改，请保留草稿并重新读取', 409,
                              id=eid, expected_revision=expected_revision, revision=actual,
                              library_revision=self.revision)

    def _apply_overlay(self, item, *, fields=None):
        eid = item['id']
        def selected(value):
            return deepcopy(value if fields is None else {k: v for k, v in value.items() if k in fields})
        result = selected(item)
        if eid in self.user_overrides:
            result.update(selected(self.user_overrides[eid]))
            result.update(is_override=True, is_user=True)
        pref = self.preferences.get(eid, {})
        preference = pref.get('preference', result.get('preference', 'neutral'))
        result.update(preference=preference, preferred=preference == 'preferred',
                      weight_boost=pref.get('weight_boost', result.get('weight_boost', 1.0)),
                      revision=self.entry_revisions.get(eid, 0), library_revision=self.revision)
        result.setdefault('is_override', False)
        result.setdefault('is_user', False)
        result.setdefault('related_ids', [])
        result['category'] = self._migrated_category(result.get('category', 'user_private'))
        result['category_label'] = self._category_label(result.get('category', 'user_private'))
        return result

    def get_entry(self, entry_id):
        with self._locked():
            eid = self._canonical_id(entry_id)
            if eid in self.deleted_ids:
                return None
            if eid in self.user_entries:
                return self._apply_overlay(self.user_entries[eid])
            item = self._base_entry(entry_id)
            return self._apply_overlay(item) if item else None

    def _entries(self, *, fields=None):
        results, seen = [], set()
        # Preserve the existing user-first / first-base-ID merge order.
        for entry in [*self.user_entries.values(), *self.base_entries]:
            eid = entry['id']
            if eid not in seen and eid not in self.deleted_ids:
                results.append(self._apply_overlay(entry, fields=fields))
                seen.add(eid)
        return results

    def _query(self, entries, *, category=None, property_id=None, property_ids=None,
               user_only=False, preferred_only=False, keyword=None, source='all', **_):
        from .user_knowledge_store import normalize_category
        if source not in {'all', 'builtin', 'user', 'override'}:
            _invalid('未知来源筛选')
        properties = property_ids.split(',') if isinstance(property_ids, str) else list(property_ids or [])
        if property_id:
            properties.append(property_id)
        targets = {property_key(value) for value in properties if str(value).strip()}
        selected_category = normalize_category(category) if category and category != 'all' else None
        needle = str(keyword or '').strip().casefold()
        results = []
        for entry in entries:
            if selected_category and entry.get('category') != selected_category:
                continue
            if user_only and not entry.get('is_user'):
                continue
            if source != 'all' and entry_source(entry) != source:
                continue
            if preferred_only and not entry.get('preferred'):
                continue
            if targets and not targets.intersection(entry_properties(entry)):
                continue
            text = ' '.join(str(entry.get(key, '')) for key in
                            ('id', 'title', 'description', 'formula', 'tags', 'properties', 'sources')).casefold()
            if needle and needle not in text:
                continue
            results.append(entry)
        return results

    def list_entries(self, category=None, property_id=None, user_only=False, preferred_only=False,
                     keyword=None, limit=100, offset=0, *, source='all', property_ids=None,
                     sort='preferred', view=None):
        if type(offset) is not int or offset < 0 or type(limit) is not int or limit < -1:
            _invalid('分页参数无效')
        if sort not in {'name', 'relevance', 'preferred', 'updated'}:
            _invalid('排序参数无效')
        if view not in {None, 'summary'}:
            _invalid('列表视图无效')
        with self._locked():
            results = self._query(self._entries(), category=category, property_id=property_id,
                user_only=user_only, preferred_only=preferred_only, keyword=keyword,
                source=source, property_ids=property_ids)
            def name_key(entry):
                return (str(entry.get('title', '')).casefold(), entry['id'])
            results.sort(key=name_key)
            if sort == 'updated':
                results.sort(key=lambda entry: str(entry.get('updated_at', '')), reverse=True)
            elif sort == 'preferred':
                results.sort(key=lambda entry: (bool(entry.get('preferred')), entry.get('weight_boost', 1),
                                               bool(entry.get('is_user'))), reverse=True)
            elif sort == 'relevance':
                needle = str(keyword or '').casefold()
                results.sort(key=lambda entry: (bool(needle and needle in entry.get('title', '').casefold()),
                                               bool(entry.get('preferred'))), reverse=True)
            total = len(results)
            paged = results[offset:offset + limit] if limit > 0 else results[offset:]
            return {'items': [entry_summary(entry) for entry in paged] if view == 'summary' else paged,
                    'total': total, 'offset': offset, 'limit': limit, 'revision': self.revision}

    def get_summary(self, *, projection='full', **filters):
        if projection not in {'full', 'stats', 'directory'}:
            _invalid('未知读取投影')
        with self._locked():
            # Query/facet inputs only: omit detail-only parameters and evidence
            # before overlay copying rather than trimming a full response.
            entries = self._entries(fields={'id', 'title', 'category', 'properties', 'description',
                'formula', 'tags', 'sources', 'is_user', 'is_override', 'preference', 'weight_boost'})
            matching = self._query(entries, **filters)
            category_filters = {key: value for key, value in filters.items() if key != 'category'}
            categories = category_facets(self._query(entries, **category_filters), self._categories(entries))
            sources = Counter(entry_source(entry) for entry in matching)
            result = {'total': len(entries), 'matched_total': len(matching), 'revision': self.revision,
                'categories': categories, 'sources': {key: sources[key] for key in ('builtin', 'user', 'override')}}
            if projection != 'stats':
                properties, counts = {}, Counter()
                for entry in entries if projection == 'directory' else matching:
                    own = entry_properties(entry)
                    properties.update(own)
                    counts.update(own.keys())
                result['properties'] = [self._property_label({**properties[key], 'count': counts[key]}) for key in sorted(properties)]
            return result

    def _property_label(self, info):
        # A display label is not a registry approval or an equivalence rule.
        return {**info, **self.property_labels.get(info.get('property_id', info.get('id', '')), {})}

    def _related_knowledge(self, entry):
        visible = {item['id']: item for item in self._entries()}
        outgoing = list(dict.fromkeys(self._canonical_id(key) for key in entry.get('related_ids', [])))
        incoming = {item['id'] for item in visible.values()
                    if entry['id'] in {self._canonical_id(key) for key in item.get('related_ids', [])}}
        related = []
        for key in dict.fromkeys([*outgoing, *sorted(incoming)]):
            if key == entry['id']:
                continue
            target = visible.get(key)
            summary = entry_summary(target) if target else {
                'id': key, 'title': '关联知识当前不可用', 'category': None, 'category_label': None}
            related.append({**summary, 'direction': 'both' if key in outgoing and key in incoming else
                            'outgoing' if key in outgoing else 'incoming',
                            'provenance': 'entry.related_ids', 'relationLabel': '用户关联',
                            'unavailable': target is None})
        return related

    def get_detail(self, entry_id):
        with self._locked():
            entry = self.get_entry(entry_id)
            if entry is None:
                return None
            parent_id = entry.get('base_id')
            # An override retains its ID; its base is the immutable original.
            if entry.get('is_override'):
                parent = next((deepcopy(item) for item in self.base_entries if item['id'] == entry['id']), None)
            else:
                parent = self.get_entry(parent_id) if parent_id else None
            entry['relations'] = {'properties': [self._property_label(info) for info in entry_properties(entry).values()],
                'base': entry_summary(parent) if parent else None,
                'base_unavailable': bool(parent_id and parent is None),
                'related': self._related_knowledge(entry),
                'derived': [entry_summary(item) for item in self._entries()
                            if item.get('base_id') == entry['id'] and item['id'] != entry['id']]}
            return entry

    def _validate(self, data, *, creating=False):
        from .user_knowledge_store import normalize_category
        if not isinstance(data, dict):
            _invalid('条目须为JSON对象')
        result = {}
        for key in ('title', 'category', 'formula', 'description', 'sources', 'base_id'):
            if key in data:
                value = data[key]
                if value is None and key == 'base_id':
                    result[key] = None
                    continue
                if not isinstance(value, str):
                    _invalid(key + '须为字符串')
                if key in {'title', 'category'} and not value.strip():
                    _invalid(key + '不能为空')
                result[key] = value.strip()
        if creating and not result.get('title'):
            _invalid('标题不能为空')
        if 'description' not in result and 'content' in data:
            if not isinstance(data['content'], str):
                _invalid('content须为字符串')
            result['description'] = data['content'].strip()
        if 'category' in result:
            result['category'] = self._resolve_category(result['category'], allow_legacy=True)
        for key in ('conditions', 'properties', 'entity_types', 'tags', 'parameters'):
            if key in data:
                value = data[key]
                allowed = (str, dict) if key == 'parameters' else (str,)
                if not isinstance(value, list) or any(not isinstance(item, allowed) for item in value):
                    _invalid(key + '须为有效数组')
                result[key] = deepcopy(value)
        if 'related_ids' in data:
            value = data['related_ids']
            if (not isinstance(value, list) or len(value) > 100
                    or any(not isinstance(key, str) or not key.strip() for key in value)):
                _invalid('related_ids须为最多100个非空知识ID的数组')
            result['related_ids'] = list(dict.fromkeys(self._canonical_id(key) for key in value))
        if 'preferred' in data and type(data['preferred']) is not bool:
            _invalid('preferred须为布尔值')
        pref = data.get('user_preference', data.get('preference'))
        if pref is None and 'preferred' in data:
            pref = 'preferred' if data['preferred'] else 'neutral'
        if pref is not None:
            if not isinstance(pref, str) or pref not in {'preferred', 'neutral', 'deprioritized'}:
                _invalid('偏好参数无效')
            result.update(preference=pref, preferred=pref == 'preferred')
        if 'weight_boost' in data:
            weight = data['weight_boost']
            if type(weight) not in {int, float} or not math.isfinite(weight) or not 0 < weight <= 100:
                _invalid('weight_boost须为0到100之间的有限数值')
            result['weight_boost'] = float(weight)
        return result

    def _validate_related_targets(self, related_ids, eid, existing=()):
        retained = {self._canonical_id(key) for key in existing}
        for key in related_ids:
            if key == eid:
                _invalid('知识条目不能关联自身')
            if key not in retained and self.get_entry(key) is None:
                _invalid('关联知识条目不存在或当前不可用')

    def _prepare_mutation(self):
        # The path lock is shared by stores in this process. Reload a newer
        # committed overlay to prevent a second application instance losing it.
        self._refresh_overlay()

    def create_user_entry(self, data):
        with self._locked():
            self._prepare_mutation()
            clean = self._validate(data, creating=True)
            raw_id = data.get('id')
            if raw_id is not None and (not isinstance(raw_id, str) or not raw_id.strip() or '/' in raw_id):
                _invalid('ID须为非空字符串且不含斜线')
            eid = raw_id.strip() if raw_id is not None else 'user_' + uuid.uuid4().hex
            if self.get_entry(eid) is not None or self._canonical_id(eid) in self.base_entries_by_id or eid in self.entry_revisions:
                raise DomainError('KNOWLEDGE_ID_CONFLICT', '条目ID已存在', 409)
            self._expect(eid, data.get('expected_revision'))
            self._validate_related_targets(clean.get('related_ids', []), eid)
            if clean.get('base_id'):
                parent = self.get_entry(clean['base_id'])
                if parent is None:
                    _invalid('派生条目的基准不可用')
                clean['base_id'] = parent['id']
            preference = clean.get('preference', 'neutral')
            item = {'id': eid, 'category': 'user_private', 'description': '', 'formula': '',
                    'conditions': [], 'parameters': [], 'properties': [], 'entity_types': [], 'tags': [], 'related_ids': [],
                    'sources': 'User Private Theory', 'base_id': None, **clean,
                    'origin': 'user', 'is_user': True, 'is_override': False, 'is_deleted': False,
                    'preference': preference, 'preferred': preference == 'preferred',
                    'weight_boost': clean.get('weight_boost', 2.0 if preference == 'preferred' else 1.0),
                    'updated_at': _now()}
            payload = self._state()
            payload['user_entries'][eid] = item
            payload['preferences'][eid] = {'preference': preference, 'weight_boost': item['weight_boost']}
            payload['cleared_preferences'] = [key for key in payload['cleared_preferences'] if key != eid]
            self._commit(payload, eid)
            return self.get_entry(eid)

    def update_entry(self, entry_id, data):
        with self._locked():
            self._prepare_mutation()
            clean = self._validate(data)
            eid = self._canonical_id(entry_id)
            current = self.get_entry(eid)
            if current is None:
                raise DomainError('KNOWLEDGE_ENTRY_NOT_FOUND', '未找到知识条目', 404)
            self._expect(eid, data.get('expected_revision'))
            if 'related_ids' in clean:
                self._validate_related_targets(clean['related_ids'], eid, current.get('related_ids', []))
            if 'base_id' in clean and clean['base_id'] != current.get('base_id'):
                _invalid('派生关系创建后不可更换')
            updated = {**current, **clean, 'updated_at': _now()}
            updated.pop('library_revision', None)
            updated.pop('revision', None)
            if eid not in self.user_entries:
                updated.update(is_override=True, is_user=True, base_id=eid)
            payload = self._state()
            payload['user_entries' if eid in self.user_entries else 'overrides'][eid] = updated
            payload['preferences'][eid] = {'preference': updated.get('preference', 'neutral'),
                                           'weight_boost': updated.get('weight_boost', 1.0)}
            payload['cleared_preferences'] = [key for key in payload['cleared_preferences'] if key != eid]
            self._commit(payload, eid)
            return self.get_entry(eid)

    def delete_entry(self, entry_id, expected_revision=None):
        with self._locked():
            self._prepare_mutation()
            eid = self._canonical_id(entry_id)
            if self.get_entry(eid) is None:
                raise DomainError('KNOWLEDGE_ENTRY_NOT_FOUND', '未找到知识条目', 404)
            self._expect(eid, expected_revision)
            payload = self._state()
            if eid in self.user_entries:
                payload['user_entries'].pop(eid)
                payload['preferences'].pop(eid, None)
            else:
                payload['deleted_ids'] = sorted(set(payload['deleted_ids']) | {eid})
            self._commit(payload, eid)
            return self._result(eid, action='deleted')

    def update_relations(self, entry_id, data):
        """Replace outgoing links and explicitly unlink visible incoming sources atomically."""
        with self._locked():
            self._prepare_mutation()
            allowed = {'related_ids', 'unlink_incoming_ids', 'expected_revision', 'expected_library_revision'}
            if not isinstance(data, dict) or set(data) - allowed or 'related_ids' not in data:
                _invalid('关联更新须为包含related_ids的有效JSON对象')
            for key in ('expected_revision', 'expected_library_revision'):
                if type(data.get(key)) is not int or data[key] < 0:
                    _invalid(key + '须为非负整数')
            outgoing = self._validate({'related_ids': data['related_ids']})['related_ids']
            unlink = data.get('unlink_incoming_ids', [])
            if (not isinstance(unlink, list)
                    or any(not isinstance(key, str) or not key.strip() for key in unlink)):
                _invalid('unlink_incoming_ids须为非空知识ID的数组')
            unlink = list(dict.fromkeys(self._canonical_id(key) for key in unlink))
            eid = self._canonical_id(entry_id)
            current = self.get_entry(eid)
            if current is None:
                raise DomainError('KNOWLEDGE_ENTRY_NOT_FOUND', '未找到知识条目', 404)
            self._expect(eid, data['expected_revision'])
            if data['expected_library_revision'] != self.revision:
                raise DomainError('KNOWLEDGE_LIBRARY_REVISION_CONFLICT', '知识库已被修改，请保留草稿并重新读取', 409,
                    id=eid, expected_library_revision=data['expected_library_revision'],
                    revision=self.entry_revisions.get(eid, 0), library_revision=self.revision)
            self._validate_related_targets(outgoing, eid, current.get('related_ids', []))
            changes = {}
            existing = list(dict.fromkeys(self._canonical_id(key) for key in current.get('related_ids', [])))
            if outgoing != existing:
                changes[eid] = (current, outgoing)
            # Resolve every source before staging anything. Hidden records and
            # entries without a real incoming edge must never be editable here.
            for source_id in unlink:
                source = self.get_entry(source_id)
                if (source_id == eid or source is None
                        or eid not in {self._canonical_id(key) for key in source.get('related_ids', [])}):
                    _invalid('只能移除当前可见的实际入向关联')
                remaining = [key for key in source['related_ids'] if self._canonical_id(key) != eid]
                changes[source_id] = (source, remaining)
            if changes:
                payload = self._state()
                for changed_id, (entry, related_ids) in changes.items():
                    collection = 'user_entries' if changed_id in self.user_entries else 'overrides'
                    # Existing raw overlay records retain their metadata and
                    # preferences; a first built-in edit follows override rules.
                    updated = deepcopy(payload[collection].get(changed_id, entry))
                    updated.pop('revision', None)
                    updated.pop('library_revision', None)
                    if collection == 'overrides':
                        updated.update(is_override=True, is_user=True, base_id=changed_id)
                    updated.update(related_ids=related_ids, updated_at=_now())
                    payload[collection][changed_id] = updated
                self._commit(payload, affected_ids=changes)
            return self._result(eid, entry=self.get_detail(eid), affected_ids=list(changes))

    def restore_default(self, entry_id, expected_revision=None):
        with self._locked():
            self._prepare_mutation()
            eid = self._canonical_id(entry_id)
            if eid not in {entry['id'] for entry in self.base_entries} or eid in self.user_entries:
                raise DomainError('KNOWLEDGE_ENTRY_NOT_FOUND', '该条目没有可恢复的内置基准', 404)
            self._expect(eid, expected_revision)
            payload = self._state()
            payload['overrides'].pop(eid, None)
            payload['preferences'].pop(eid, None)
            # Remember an explicitly cleared seed without treating it as an
            # active user preference after a later load.
            payload['cleared_preferences'] = sorted(set(payload['cleared_preferences']) | {eid})
            payload['deleted_ids'] = [key for key in payload['deleted_ids'] if key != eid]
            self._commit(payload, eid)
            return self._result(eid, action='restored', entry=self.get_entry(eid))

    def _result(self, eid, **extra):
        return {'success': True, 'id': eid, 'revision': self.entry_revisions.get(eid, 0),
                'library_revision': self.revision, **extra}

    def set_preference(self, entry_id, preference, weight_boost=None, expected_revision=None):
        data = {'preference': preference}
        if weight_boost is not None:
            data['weight_boost'] = weight_boost
        clean = self._validate(data)
        if 'preference' not in clean:
            _invalid('偏好不能为空')
        weight = clean.get('weight_boost', 2.0 if preference == 'preferred' else 0.2 if preference == 'deprioritized' else 1.0)
        with self._locked():
            self._prepare_mutation()
            eid = self._canonical_id(entry_id)
            if self.get_entry(eid) is None:
                raise DomainError('KNOWLEDGE_ENTRY_NOT_FOUND', '未找到知识条目', 404)
            self._expect(eid, expected_revision)
            payload = self._state()
            payload['preferences'][eid] = {'preference': preference, 'weight_boost': weight}
            payload['cleared_preferences'] = [key for key in payload['cleared_preferences'] if key != eid]
            self._commit(payload, eid)
            return self._result(eid, entry=self.get_entry(eid), preference=preference, weight_boost=weight)

    def get_preferred_ids(self):
        with self._locked():
            return {entry['id'] for entry in self._entries() if entry.get('preferred')}

    def resolve_cached_block(self, block):
        """Apply the active overlay to a cached theory without reviving tombstones."""
        claim = block.get('claim') or {}
        candidates = [block.get('entry_id'), block.get('theory_id'), claim.get('claim_id')]
        for value in list(candidates):
            if isinstance(value, str):
                for prefix in ('kb-theory-', 'kb-'):
                    if value.startswith(prefix):
                        candidates.append(value[len(prefix):])
        with self._locked():
            for value in candidates:
                if not value:
                    continue
                eid = self._canonical_id(value)
                known = eid in self.user_entries or eid in self.base_entries_by_id or eid in self.entry_revisions
                if not known:
                    continue
                entry = self.get_entry(eid)
                if entry is None:
                    return None
                result = self.to_knowledge_block(entry)
                if claim.get('claim_id'):
                    result['claim']['claim_id'] = claim['claim_id']
                return result
        return deepcopy(block)

    def search(self, field_names=None, entity_types=None, keywords=None, categories=None, top_k=5,
               user_only=False, preferred_only=False):
        from .user_knowledge_store import normalize_category
        fields = {property_key(value) for value in field_names or [] if value}
        entities = {str(value).casefold() for value in entity_types or [] if value}
        category_ids = {normalize_category(value) for value in categories or [] if value}
        needles = [str(value).casefold() for value in keywords or [] if value]
        ranked = []
        for entry in self.list_entries(user_only=user_only, preferred_only=preferred_only, limit=-1)['items']:
            score = 6.0 * len(fields.intersection(entry_properties(entry)))
            score += 3.5 * len(entities.intersection(str(value).casefold() for value in entry.get('entity_types', [])))
            score += 2.5 if entry.get('category') in category_ids else 0
            text = ' '.join(str(entry.get(key, '')) for key in ('title', 'id', 'description', 'tags')).casefold()
            score += sum(3.0 for needle in needles if needle in text)
            if entry.get('preferred'):
                score += 8.0 * max(1, entry.get('weight_boost', 1))
            elif entry.get('preference') == 'deprioritized':
                score -= 8.0 / max(.1, entry.get('weight_boost', 1))
            if entry.get('is_user'):
                score += 2.0
            if score > .5:
                ranked.append((score, entry))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in ranked[:top_k]]

    def get_graph(self, category=None, property_id=None, user_only=False, preferred_only=False,
                  keyword=None, *, source='all', property_ids=None, sort='preferred', view=None,
                  focus_id=None, limit=80):
        from .user_knowledge_store import KNOWLEDGE_CATEGORIES
        if view not in {None, 'overview', 'category', 'focus'}:
            _invalid('图谱视图无效')
        if type(limit) is not int or not 1 <= limit <= 200:
            _invalid('图谱节点上限须介于1与200之间')
        with self._locked():
            entries = self.list_entries(category, property_id, user_only, preferred_only, keyword,
                limit=-1, source=source, property_ids=property_ids, sort=sort)['items']
            graph = graph_projection(entries, self._categories(), total_entries=len(self._entries()),
                revision=self.revision, view=view or 'category', focus_id=self._canonical_id(focus_id),
                limit=200 if view is None else limit, legacy=view is None)
            graph['nodes'] = [self._property_label(node) if node['kind'] == 'property' else node for node in graph['nodes']]
            return graph
