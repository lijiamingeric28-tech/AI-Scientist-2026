"""HTTP adapter: all views and writes share one registry workbench domain."""
from typing import Literal

from fastapi import Depends, FastAPI, Query, Request
from astroquery_ai.api.read_caching import conditional_json
from astroquery_ai.runtime.errors import DomainError


def register(app: FastAPI, application, scheduler=None):
    store = application.registry_workbench
    prefix = '/api/registry-workbench'

    def filters(workspace_id: str | None = None, release_id: str | None = None,
                keyword: str | None = None, type_id: str | None = None, family_id: str | None = None,
                origin: str | None = None, status: str | None = None, sort: str = 'label'):
        return dict(workspace_id=workspace_id, release_id=release_id, keyword=keyword, type_id=type_id,
                    family_id=family_id, origin=origin, status=status, sort=sort)

    async def body(request):
        try:
            payload = await request.json()
        except (ValueError, UnicodeError) as exc:
            raise DomainError('INVALID_JSON', '请求体JSON格式错误', 422) from exc
        if not isinstance(payload, dict):
            raise DomainError('INVALID_PAYLOAD', '请求体必须是对象', 422)
        return payload

    def require(payload, keys):
        if any(k not in payload for k in keys):
            raise DomainError('MISSING_FIELDS', '请求缺少必要并发校验字段', 422, fields=list(keys))

    @app.get(prefix + '/summary')
    def summary(request: Request, query: dict = Depends(filters), projection: Literal['full', 'stats', 'directory'] | None = None):
        result = store.summary(**query, projection=projection or 'full')
        return conditional_json(request, result, namespace='registry-summary/1') if projection else result

    @app.get(prefix + '/graph')
    def graph(query: dict = Depends(filters), view: str = 'overview', focus_id: str | None = None, limit: int = Query(80, ge=1, le=200)):
        return store.graph(**query, view=view, focus_id=focus_id, limit=limit)

    @app.get(prefix + '/workspaces')
    def workspaces(request: Request, projection: Literal['full', 'directory'] | None = None):
        result = store.list_workspaces(projection=projection or 'full')
        return conditional_json(request, result, namespace='registry-workspaces/1') if projection else result

    @app.post(prefix + '/workspaces')
    async def create_workspace(request: Request):
        return store.create_workspace((await body(request)).get('base_bundle_id'))

    @app.get(prefix + '/workspaces/{workspace_id}')
    def workspace(workspace_id: str):
        return store.get_workspace(workspace_id)

    @app.post(prefix + '/workspaces/{workspace_id}/validate')
    async def validate(workspace_id: str, request: Request):
        payload = await body(request); require(payload, ('expected_revision',))
        return store.validate(workspace_id, expected_revision=payload['expected_revision'])

    @app.post(prefix + '/workspaces/{workspace_id}/publish')
    async def publish(workspace_id: str, request: Request):
        payload = await body(request)
        keys = ('expected_revision', 'validation_id', 'expected_active_bundle_id', 'idempotency_key')
        require(payload, keys)
        return store.publish(workspace_id, **{k: payload[k] for k in keys})

    @app.get(prefix + '/releases')
    def releases(request: Request, projection: Literal['full', 'directory'] | None = None):
        result = store.list_releases(projection=projection or 'full')
        return conditional_json(request, result, namespace='registry-releases/1') if projection else result

    @app.post(prefix + '/releases/{release_id}/activate')
    async def activate(release_id: str, request: Request):
        payload = await body(request); keys = ('expected_active_bundle_id', 'idempotency_key'); require(payload, keys)
        return store.activate(release_id, **{k: payload[k] for k in keys})

    @app.get(prefix + '/workspaces/{workspace_id}/{kind}/{item_id}/impact')
    def impact(workspace_id: str, kind: str, item_id: str):
        return store.impact(workspace_id, kind, item_id)

    @app.post(prefix + '/workspaces/{workspace_id}/{kind}')
    async def create(workspace_id: str, kind: str, request: Request):
        payload = await body(request); revision = payload.pop('expected_revision', None)
        return store.write(workspace_id, kind, payload, expected_revision=revision)

    @app.put(prefix + '/workspaces/{workspace_id}/{kind}/{item_id}')
    async def update(workspace_id: str, kind: str, item_id: str, request: Request):
        payload = await body(request); revision = payload.pop('expected_revision', None)
        return store.write(workspace_id, kind, payload, item_id=item_id, expected_revision=revision)

    @app.delete(prefix + '/workspaces/{workspace_id}/{kind}/{item_id}')
    async def delete(workspace_id: str, kind: str, item_id: str, request: Request, expected_revision: int | None = Query(None, ge=1)):
        if expected_revision is None and await request.body():
            expected_revision = (await body(request)).get('expected_revision')
        return store.delete(workspace_id, kind, item_id, expected_revision=expected_revision)

    @app.get(prefix + '/knowledge/{entry_id}')
    def knowledge_detail(entry_id: str, workspace_id: str | None = None, release_id: str | None = None):
        return store.knowledge_detail(entry_id, workspace_id=workspace_id, release_id=release_id)

    @app.get(prefix + '/{kind}/{item_id}')
    def detail(kind: str, item_id: str, workspace_id: str | None = None, release_id: str | None = None):
        return store.detail(kind, item_id, workspace_id=workspace_id, release_id=release_id)

    @app.get(prefix + '/{kind}')
    def listing(kind: str, query: dict = Depends(filters), offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        return store.list_items(kind, **query, offset=offset, limit=limit)
