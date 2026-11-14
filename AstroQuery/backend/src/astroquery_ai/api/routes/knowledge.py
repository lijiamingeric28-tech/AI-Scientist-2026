"""HTTP adapter for the application-scoped knowledge workbench."""
from __future__ import annotations

from typing import Literal

from fastapi import Depends, FastAPI, Query, Request

from astroquery_ai.api.read_caching import conditional_json
from astroquery_ai.runtime.errors import DomainError


def register(app: FastAPI, application, scheduler) -> None:
    store = application.user_knowledge

    def common_filters(
        category: str | None = None,
        property_id: str | None = None,
        property_ids: str | None = None,
        source: Literal['all', 'builtin', 'user', 'override'] = 'all',
        user_only: bool = False,
        preferred_only: bool = False,
        keyword: str | None = None,
    ):
        return dict(category=category, property_id=property_id, property_ids=property_ids,
                    source=source, user_only=user_only, preferred_only=preferred_only, keyword=keyword)

    async def body(request):
        try:
            value = await request.json()
        except (ValueError, UnicodeError) as exc:
            raise DomainError('INVALID_JSON', '请求体JSON格式错误', 422) from exc
        if not isinstance(value, dict):
            raise DomainError('INVALID_PAYLOAD', '请求体必须为JSON对象', 422)
        return value

    @app.get('/api/knowledge')
    def list_knowledge(
        filters: dict = Depends(common_filters),
        limit: int = Query(default=100, ge=-1, le=2000),
        offset: int = Query(default=0, ge=0),
        sort: Literal['name', 'relevance', 'preferred', 'updated'] = 'preferred',
        view: Literal['summary'] | None = None,
    ):
        return store.list_entries(**filters, limit=limit, offset=offset, sort=sort, view=view)

    # Static paths must precede the generic entry route.
    @app.get('/api/knowledge/categories')
    def categories():
        return store.get_categories()

    @app.post('/api/knowledge/categories')
    async def create_category(request: Request):
        return store.create_category(await body(request))

    @app.post('/api/knowledge/categories/order')
    async def reorder_categories(request: Request):
        return store.reorder_categories(await body(request))

    @app.put('/api/knowledge/categories/{category_id:path}')
    async def rename_category(category_id: str, request: Request):
        return store.rename_category(category_id, await body(request))

    @app.delete('/api/knowledge/categories/{category_id:path}')
    def delete_category(category_id: str, expected_revision: int | None = Query(default=None, ge=0),
                        target_category: str = 'user_private'):
        return store.delete_category(category_id, expected_revision=expected_revision, target_category=target_category)

    @app.get('/api/knowledge/summary')
    def summary(request: Request, filters: dict = Depends(common_filters), projection: Literal['full', 'stats', 'directory'] | None = None):
        result = store.get_summary(**filters, projection=projection or 'full')
        return conditional_json(request, result, namespace='knowledge-summary/1') if projection else result

    @app.get('/api/knowledge/graph')
    def graph(
        filters: dict = Depends(common_filters),
        view: Literal['overview', 'category', 'focus'] | None = None,
        focus_id: str | None = None,
        limit: int = Query(default=80, ge=1, le=200),
        sort: Literal['name', 'relevance', 'preferred', 'updated'] = 'preferred',
    ):
        return store.get_graph(**filters, view=view, focus_id=focus_id, limit=limit, sort=sort)

    @app.get('/api/knowledge/{entry_id}')
    def detail(entry_id: str):
        entry = store.get_detail(entry_id)
        if entry is None:
            raise DomainError('KNOWLEDGE_ENTRY_NOT_FOUND', '未找到理论知识条目', 404)
        return entry

    @app.post('/api/knowledge')
    async def create(request: Request):
        return store.create_user_entry(await body(request))

    @app.put('/api/knowledge/{entry_id}')
    async def update(entry_id: str, request: Request):
        return store.update_entry(entry_id, await body(request))

    @app.put('/api/knowledge/{entry_id}/relations')
    async def update_relations(entry_id: str, request: Request):
        return store.update_relations(entry_id, await body(request))

    @app.delete('/api/knowledge/{entry_id}')
    def delete(entry_id: str, expected_revision: int | None = Query(default=None, ge=0), restore: bool = False):
        # Retain the old explicit restore query for older clients.
        operation = store.restore_default if restore else store.delete_entry
        return operation(entry_id, expected_revision=expected_revision)

    @app.post('/api/knowledge/{entry_id}/restore')
    async def restore(entry_id: str, request: Request):
        payload = await body(request) if await request.body() else {}
        return store.restore_default(entry_id, expected_revision=payload.get('expected_revision'))

    @app.post('/api/knowledge/{entry_id}/preference')
    async def preference(entry_id: str, request: Request):
        payload = await body(request)
        pref = payload.get('preference')
        if pref is None and 'preferred' in payload:
            if type(payload['preferred']) is not bool:
                raise DomainError('KNOWLEDGE_INVALID_INPUT', 'preferred须为布尔值', 422)
            pref = 'preferred' if payload['preferred'] else 'neutral'
        return store.set_preference(entry_id, pref or 'neutral', payload.get('weight_boost'),
                                    expected_revision=payload.get('expected_revision'))
