"""Category metadata and migrations in the workbench's atomic user overlay."""
from __future__ import annotations

import re
import uuid
from collections import Counter
from copy import deepcopy

from astroquery_ai.runtime.errors import DomainError


class KnowledgeCategoriesMixin:
    def _migrated_category(self, category):
        # Base records are immutable. Remember category migrations separately so
        # restoring their source text cannot restore a deleted classification.
        seen = set()
        while category in self.category_redirects and category not in seen:
            seen.add(category)
            category = self.category_redirects[category]
        return category

    def _infer_categories(self, registered, records, deleted):
        from .user_knowledge_store import KNOWLEDGE_CATEGORIES, normalize_category
        result = deepcopy(registered)
        builtins = {item['id'] for item in KNOWLEDGE_CATEGORIES}
        for item in records:
            category = normalize_category(item.get('category', 'user_private'))
            if category not in builtins and category not in deleted and category not in result:
                result[category] = {'id': category, 'label': category, 'color': '#0ea5e9',
                                    'is_custom': True, 'revision': 0}
        return result

    def _custom_category_registry(self):
        return self._infer_categories(self.custom_categories,
            [*self.base_entries, *self.user_entries.values(), *self.user_overrides.values()],
            self.deleted_category_ids)

    def _category_definitions(self):
        from .user_knowledge_store import KNOWLEDGE_CATEGORIES
        custom = self._custom_category_registry()
        definitions = {item['id']: {**deepcopy(item), 'is_custom': False, 'revision': 0,
                                  **self.category_appearance.get(item['id'], {})}
                       for item in KNOWLEDGE_CATEGORIES}
        definitions.update(custom)
        return [{**definitions[category_id], 'order': index} for index, category_id in
                enumerate(self._ordered_category_ids(custom, self.category_order))]

    def _ordered_category_ids(self, custom, order):
        from .user_knowledge_store import KNOWLEDGE_CATEGORIES
        fallback = [item['id'] for item in KNOWLEDGE_CATEGORIES] + sorted(custom)
        known = set(fallback)
        return list(dict.fromkeys([key for key in order if key in known] + fallback))

    def _category_label(self, category):
        from .user_knowledge_store import KNOWLEDGE_CATEGORIES
        if category in self.custom_categories:
            return self.custom_categories[category]['label']
        return next((item['label'] for item in KNOWLEDGE_CATEGORIES if item['id'] == category), category)

    def _resolve_category(self, value, *, allow_legacy=False):
        from .user_knowledge_store import normalize_category
        category = normalize_category(value)
        definitions = self._category_definitions()
        if category in {item['id'] for item in definitions}:
            return category
        if category in self.deleted_category_ids:
            raise DomainError('KNOWLEDGE_CATEGORY_NOT_FOUND', '分类已删除，请重新选择分类', 422, id=category)
        for item in definitions:
            if item['label'].casefold() == category.casefold():
                return item['id']
        if allow_legacy and not category.startswith('custom_'):
            self._validate_category_label({'label': category})
            return category
        raise DomainError('KNOWLEDGE_CATEGORY_NOT_FOUND', '分类不存在，请重新选择分类', 422, id=category)

    def _category_references(self):
        # Include hidden entries; user records retain the normal user-first merge.
        entries = {item['id']: item for item in reversed(self.base_entries)}
        entries.update(self.user_entries)
        for eid, override in self.user_overrides.items():
            entries[eid] = {**entries.get(eid, {'id': eid}), **override}
        return [{**item, 'category': self._migrated_category(item.get('category', 'user_private'))}
                for item in entries.values()]

    def _categories(self, entries=None):
        if entries is None:
            entries = self._entries()
        visible = Counter(item.get('category', 'user_private') for item in entries)
        references = Counter(item.get('category', 'user_private') for item in self._category_references())
        return [{**item, 'count': visible[item['id']], 'entry_count': references[item['id']]}
                for item in self._category_definitions()]

    def get_categories(self):
        with self._locked():
            return {'items': self._categories(), 'revision': self.revision}

    def _validate_category_label(self, data, *, category_id=None):
        if not isinstance(data, dict) or not isinstance(data.get('label'), str):
            raise DomainError('KNOWLEDGE_INVALID_INPUT', '分类名称须为字符串', 422)
        label = data['label'].strip()
        if not 1 <= len(label) <= 40 or any(ord(char) < 32 or ord(char) == 127 for char in label):
            raise DomainError('KNOWLEDGE_INVALID_INPUT', '分类名称须为1至40个字符的单行文本', 422)
        for item in self._category_definitions():
            names = (item['label'],) if item['is_custom'] else (item['id'], item['label'], *item.get('alt_names', []))
            if item['id'] != category_id and label.casefold() in {name.casefold() for name in names}:
                raise DomainError('KNOWLEDGE_CATEGORY_CONFLICT', '分类名称已存在', 409)
        return label

    def _editable_category(self, category_id, expected_revision, *, allow_builtin=False):
        category = next((item for item in self._category_definitions() if item['id'] == category_id), None)
        if category is None:
            raise DomainError('KNOWLEDGE_CATEGORY_NOT_FOUND', '分类不存在', 404, id=category_id)
        if not category['is_custom'] and not allow_builtin:
            raise DomainError('KNOWLEDGE_CATEGORY_IMMUTABLE', '内置分类不能重命名或删除', 422, id=category_id)
        if expected_revision is not None:
            if type(expected_revision) is not int or expected_revision < 0:
                raise DomainError('KNOWLEDGE_INVALID_INPUT', 'expected_revision须为非负整数', 422)
            if expected_revision != category['revision']:
                raise DomainError('KNOWLEDGE_CATEGORY_REVISION_CONFLICT', '分类已被修改，请重新读取', 409,
                    id=category_id, expected_revision=expected_revision, revision=category['revision'],
                    library_revision=self.revision)
        return category

    def _validate_category_color(self, color):
        if not isinstance(color, str) or re.fullmatch(r'#[0-9a-fA-F]{6}', color) is None:
            raise DomainError('KNOWLEDGE_INVALID_INPUT', '分类颜色须为#RRGGBB格式', 422)
        return color.lower()

    def create_category(self, data):
        with self._locked():
            label = self._validate_category_label(data)
            color = self._validate_category_color(data.get('color', '#0ea5e9'))
            category_id = 'custom_' + uuid.uuid4().hex
            payload = self._state()
            payload['custom_categories'][category_id] = {'id': category_id, 'label': label,
                'color': color, 'is_custom': True, 'revision': 1}
            payload['category_order'].append(category_id)
            self._commit(payload)
            return {'success': True, 'category': next(item for item in self._categories() if item['id'] == category_id),
                    'revision': self.revision}

    def rename_category(self, category_id, data):
        with self._locked():
            if not isinstance(data, dict):
                raise DomainError('KNOWLEDGE_INVALID_INPUT', '分类须为JSON对象', 422)
            category = self._editable_category(category_id, data.get('expected_revision'), allow_builtin=True)
            if 'label' not in data and 'color' not in data:
                raise DomainError('KNOWLEDGE_INVALID_INPUT', '须提供分类名称或颜色', 422)
            if 'label' in data and not category['is_custom']:
                raise DomainError('KNOWLEDGE_CATEGORY_IMMUTABLE', '内置分类不能重命名或删除', 422, id=category_id)
            label = self._validate_category_label(data, category_id=category_id) if 'label' in data else category['label']
            color = self._validate_category_color(data['color']) if 'color' in data else category['color']
            payload = self._state()
            if category['is_custom']:
                payload['custom_categories'][category_id] = {**category, 'label': label, 'color': color,
                                                             'revision': category['revision'] + 1}
            else:
                payload['category_appearance'][category_id] = {'color': color, 'revision': category['revision'] + 1}
            self._commit(payload)
            return {'success': True, 'category': next(item for item in self._categories() if item['id'] == category_id),
                    'revision': self.revision}

    def reorder_categories(self, data):
        with self._locked():
            if not isinstance(data, dict) or type(data.get('expected_revision')) is not int or data['expected_revision'] < 0:
                raise DomainError('KNOWLEDGE_INVALID_INPUT', 'expected_revision须为非负整数', 422)
            if data['expected_revision'] != self.revision:
                raise DomainError('KNOWLEDGE_LIBRARY_REVISION_CONFLICT', '知识库已被修改，请重新读取', 409,
                                  expected_revision=data['expected_revision'], revision=self.revision,
                                  library_revision=self.revision)
            ids = data.get('ids')
            current = {item['id'] for item in self._category_definitions()}
            if (not isinstance(ids, list) or any(not isinstance(key, str) for key in ids)
                    or len(ids) != len(current) or len(set(ids)) != len(ids) or set(ids) != current):
                raise DomainError('KNOWLEDGE_INVALID_INPUT', '须按顺序提供全部分类且不能重复', 422)
            payload = self._state()
            payload['category_order'] = list(ids)
            self._commit(payload)
            return {'success': True, 'items': self._categories(), 'revision': self.revision}

    def delete_category(self, category_id, *, expected_revision=None, target_category='user_private'):
        with self._locked():
            self._editable_category(category_id, expected_revision)
            if not isinstance(target_category, str) or not target_category.strip():
                raise DomainError('KNOWLEDGE_INVALID_INPUT', '须选择迁移分类', 422)
            target = self._resolve_category(target_category)
            if target == category_id:
                raise DomainError('KNOWLEDGE_INVALID_INPUT', '迁移分类不能与删除分类相同', 422)
            payload = self._state()
            affected = set()
            for collection in ('user_entries', 'overrides'):
                for eid, item in payload[collection].items():
                    if item.get('category') == category_id:
                        item['category'] = target
                        item.pop('category_label', None)
                        affected.add(eid)
            # An older corpus can itself contain a custom category. Migrate by
            # an override so immutable scientific source files stay untouched.
            for item in self._category_references():
                eid = item['id']
                if item.get('category') == category_id and eid not in affected:
                    payload['overrides'][eid] = {**deepcopy(item), 'category': target,
                                                'is_override': True, 'is_user': True}
                    affected.add(eid)
            payload['custom_categories'].pop(category_id)
            payload['category_order'] = [key for key in payload['category_order'] if key != category_id]
            payload['deleted_category_ids'] = sorted(set(payload['deleted_category_ids']) | {category_id})
            payload['category_redirects'][category_id] = target
            self._commit(payload, affected_ids=affected)
            return {'success': True, 'id': category_id, 'target_category': target,
                    'moved_count': len(affected), 'revision': self.revision}
