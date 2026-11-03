"""Small task-scoped official route selector, using the normal HTTP ledger."""
from __future__ import annotations

import asyncio
import time

from .codec import digest
from .errors import DomainError


def retryable(exc):
    return isinstance(exc, DomainError) and (
        exc.code in {'SOURCE_HTTP_TIMEOUT', 'SOURCE_TRANSPORT_ERROR'} or
        exc.code == 'SOURCE_HTTP_ERROR' and (exc.details.get('provider_status', 0) >= 500
                                           or exc.details.get('provider_status') == 429))


class ServiceRoutes:
    def __init__(self, http, *, health_service=None):
        self.http = http
        self.health_service = health_service
        self.root = http.steps.app.http if hasattr(http, 'steps') else http
        self.repo = getattr(self.root, 'repository', None)
        if not hasattr(self.root, 'route_states'):
            self.root.route_states, self.root.route_locks = {}, {}

    def state(self, tid, service, capability):
        service = self.health_service or service
        key = (tid, service, capability)
        if key not in self.root.route_states:
            value = None
            if self.repo:
                with self.repo.read() as conn:
                    value = next((x for x in self.repo.objects(conn, tid, 'service_route')
                                  if x['service'] == service and x['capability'] == capability), None)
            self.root.route_states[key] = value or {'service': service, 'capability': capability,
                'revision': 0, 'nodes': {}, 'preferred': None, 'probed': False}
        return self.root.route_states[key]

    def save(self, tid, state):
        state['revision'] += 1
        if self.repo:
            with self.repo.transaction() as conn:
                self.repo.put_object(conn, tid, 'service_route',
                    'route-' + digest([state['service'], state['capability']]), state['revision'], state)

    async def probe(self, tid, owner, service, capability, endpoints, params):
        key = (tid, self.health_service or service, capability)
        async with self.root.route_locks.setdefault(key, asyncio.Lock()):
            state = self.state(tid, service, capability)
            if state['probed']:
                if state.get('unavailable_until', 0) > time.time():
                    raise DomainError('CATALOG_ENDPOINTS_UNAVAILABLE', '官方表服务两轮探测均失败', attempts=state.get('probe_failures', []))
                if state.get('preferred'):
                    return
            failures = []
            for round_index in range(2):
                async def one(endpoint):
                    started = time.monotonic()
                    try:
                        raw, metadata = await self.http.request(tid, owner, service, 'GET', endpoint,
                            params=params, timeout=8, connect_timeout=4, read_timeout=8,
                            max_bytes=1024**2,managed_routes=True)
                        # An HTML error page is not a working VOTable protocol.
                        if b'VOTABLE' not in raw.upper():
                            raise DomainError('SOURCE_PROTOCOL_UNAVAILABLE', '该入口没有返回VOTable')
                        return endpoint, time.monotonic() - started, None
                    except DomainError as exc:
                        if not retryable(exc) and exc.code not in {'SOURCE_PROTOCOL_UNAVAILABLE', 'SOURCE_REDIRECT_LIMIT'}:
                            raise
                        return endpoint, None, exc
                results = await asyncio.gather(*(one(e) for e in endpoints))
                successes = []
                for endpoint, duration, exc in results:
                    if exc is None:
                        state['nodes'][endpoint] = {'last_success': time.time(), 'seconds': duration, 'cool_until': 0}
                        successes.append((duration, endpoint))
                    else:
                        failures.append({'endpoint': endpoint, 'round': round_index + 1, 'reason': exc.code})
                        state['nodes'][endpoint] = {'cool_until': time.time() + 60, 'reason': exc.code}
                        if exc.details.get('provider_status') == 429:
                            # A service rate refusal is not permission to move sites.
                            state['probed'] = False
                            self.save(tid, state)
                            raise exc
                if successes:
                    state.update(preferred=min(successes)[1], probed=True, probe_failures=failures,
                                 unavailable_until=0)
                    self.save(tid, state)
                    return
                if round_index == 0:
                    await asyncio.sleep(1)
            state.update(probed=True, preferred=None, probe_failures=failures,
                         unavailable_until=time.time() + 60)
            self.save(tid, state)
            raise DomainError('CATALOG_ENDPOINTS_UNAVAILABLE', '官方表服务两轮探测均失败', attempts=failures)

    async def request(self, tid, owner, service, capability, endpoints, method, **kwargs):
        kwargs['managed_routes']=True
        state = self.state(tid, service, capability)
        scope = digest(sorted(endpoints))
        key = (tid,self.health_service or service,capability)
        def unavailable():
            if state.get('unavailable_until',0) > time.time() and state.get('unavailable_scope',scope) == scope:
                raise DomainError('IDENTITY_ENDPOINTS_UNAVAILABLE' if service=='simbad' else 'CATALOG_ENDPOINTS_UNAVAILABLE',
                    '本任务同协议两轮访问失败，冷却期内没有重复别名请求',
                    attempts=state.get('probe_failures',[]), shared_unavailable=True,
                    retry_after_seconds=max(0,state['unavailable_until']-time.time()))
        def failed(endpoint,exc,round_index):
            # A redirect-only endpoint is unavailable for this protocol. It
            # must not abort/cancel healthy sibling probes or erase their result.
            capability_failure = exc.code in {'SOURCE_REDIRECT_LIMIT', 'SOURCE_PROTOCOL_UNAVAILABLE'} or (
                capability == 'readme_text' and exc.code == 'SOURCE_HTTP_ERROR'
                and exc.details.get('provider_status') == 404)
            if not retryable(exc) and not capability_failure:
                raise exc
            if exc.details.get('provider_status') == 429:
                raise exc  # Retry-After remains service-wide; never rotate to evade it.
            state['nodes'][endpoint] = {'cool_until':time.time()+60,'reason':exc.code}
            self.save(tid,state)
            return {'endpoint':endpoint,'round':round_index+1,'reason':exc.code}
        def succeeded(endpoint,raw,metadata,started,failures):
            state.update(preferred=endpoint,unavailable_until=0,unavailable_scope=None)
            state['nodes'][endpoint]={'last_success':time.time(),'seconds':time.monotonic()-started,'cool_until':0}
            self.save(tid,state)
            return raw,{**metadata,'selected_route':endpoint,'prior_endpoint_failures':failures,
                        'route_capability':capability}
        unavailable()
        failures = []
        tried=set()
        preferred=state.get('preferred')
        # Healthy calls remain parallel. Only route recovery is coalesced.
        if preferred in endpoints and state['nodes'].get(preferred,{}).get('cool_until',0)<=time.time():
            started=time.monotonic()
            try:
                raw,metadata=await self.http.request(tid,owner,service,method,preferred,**kwargs)
                return succeeded(preferred,raw,metadata,started,failures)
            except DomainError as exc:
                failures.append(failed(preferred,exc,0));tried.add(preferred)
        async with self.root.route_locks.setdefault(key,asyncio.Lock()):
            unavailable()
            preferred=state.get('preferred')
            ordered=list(dict.fromkeys(([preferred] if preferred in endpoints else [])+list(endpoints)))
            for round_index in range(2):
                for endpoint in ordered:
                    if round_index==0 and (endpoint in tried or state['nodes'].get(endpoint,{}).get('cool_until',0)>time.time()):
                        continue
                    started=time.monotonic()
                    try:
                        raw,metadata=await self.http.request(tid,owner,service,method,endpoint,**kwargs)
                    except DomainError as exc:
                        failures.append(failed(endpoint,exc,round_index));continue
                    return succeeded(endpoint,raw,metadata,started,failures)
                if round_index==0:
                    await asyncio.sleep(1)
            state.update(preferred=None,unavailable_until=time.time()+60,unavailable_scope=scope,
                         probe_failures=failures,probed=True)
            self.save(tid,state)
            raise DomainError('IDENTITY_ENDPOINTS_UNAVAILABLE' if service=='simbad' else 'CATALOG_ENDPOINTS_UNAVAILABLE',
                '官方来源两轮请求仍不可用',attempts=failures,shared_unavailable=True,retry_after_seconds=60)
