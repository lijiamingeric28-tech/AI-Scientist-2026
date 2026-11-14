"""Durable successful job steps; resuming a job does not repeat completed I/O."""

from dataclasses import asdict

from .codec import digest
from .errors import DomainError


class JobSteps:
    def __init__(self, application):
        self.app, self.repo = application, application.repository

    def load(self, execution, key):
        with self.repo.read() as conn:
            self.repo.validate_lease(conn, execution, scientific=False)
            try:
                return self.repo.object(conn, execution["task_id"], "job_step", key)
            except DomainError as exc:
                if exc.code != "OBJECT_NOT_FOUND":
                    raise
                return None

    def save(self, execution, key, body, artifact=None):
        with self.repo.transaction() as conn:
            self.repo.validate_lease(conn, execution, scientific=False)
            if artifact:
                self.app.artifacts.register(conn, execution["task_id"], key, artifact)
            self.repo.put_object(conn, execution["task_id"], "job_step", key, 1, body)

    async def model(self, execution, **kwargs):
        cache_only = kwargs.pop('cache_only', False)
        bindings = kwargs.pop('bindings', None)
        # A failure budget belongs to one concrete job operation, not every
        # successful child window that inherited a parent's root identifier.
        if execution['kind'] == 'paper_batch' and execution['payload'].get('reading_batch_id'):
            kwargs['root_id'] = 'reading:' + execution['payload']['reading_batch_id']
            kwargs['root_limit'] = 2
        else:
            kwargs['root_id'] = ':'.join((kwargs['root_id'], execution['job_id'], kwargs['profile'].operation))
        profile_key = asdict(kwargs['profile'])
        if bindings is not None:
            body={'job_id':execution['job_id'], 'bindings':bindings,
                  'input_hash':digest(kwargs['messages']), 'profile_version':kwargs['profile'].version}
            with self.repo.transaction() as conn:
                self.repo.validate_lease(conn,execution,scientific=False)
                self.repo.put_object(conn,execution['task_id'],'model_binding','binding-'+digest(body),1,body)
        if execution['kind'] in {'catalog_discover', 'catalog_extract'}:
            from .run_policy import catalog_window
            with self.repo.read() as conn:
                controlled = catalog_window(self.repo, conn, execution['task_id']) is not None
            if controlled:
                # Remaining-window timeouts do not change provider/model inputs.
                # Successful paid steps remain reusable after resource waiting.
                profile_key = {k: v for k, v in profile_key.items() if k not in {'wall_seconds', 'inactivity_seconds'}}
        key = "step-" + digest(
            {
                "job": execution["job_id"],
                "kind": "model",
                "owner": kwargs["owner"],
                "root": kwargs["root_id"],
                "messages": kwargs["messages"],
                "profile": profile_key,
                **({'bindings': bindings} if bindings is not None else {}),
            }
        )
        previous = self.load(execution, key)
        if previous:
            return previous["response"], previous["receipt"]
        if cache_only:
            raise DomainError('CATALOG_SELECTION_CLOSED', '初筛窗口已结束且此步骤没有已保存响应')
        if execution['kind'] == 'catalog_extract':
            with self.repo.read() as conn:
                attempted = conn.execute("SELECT 1 FROM attempts WHERE task_id=? AND root_id=? AND status<>'not_dispatched' LIMIT 1",
                                         (execution['task_id'], kwargs['root_id'])).fetchone()
            if attempted:
                from .run_policy import claim_table_repair
                if not claim_table_repair(self.repo, execution):
                    raise DomainError('CATALOG_TABLE_REPAIR_EXHAUSTED', '本表已用一次备用或修复，保留原件及已完成结果')
        while True:
            try:
                response, receipt = await self.app.models.json(**kwargs)
                break
            except Exception as exc:
                from .throughput import DispatchDeferred
                if not isinstance(exc,DispatchDeferred) or execution['kind'] not in {
                    'literature_discover','material_prepare','citation_enrich','compare_results','insights'
                }:
                    raise
                # Internal parallel units share a coordinator lease. Keep this
                # exact pending call/input in place so siblings can checkpoint;
                # a rate wait is neither a content retry nor a new paid call.
                import asyncio
                with self.repo.transaction() as conn:
                    self.repo.validate_lease(conn,execution,scientific=False)
                    self.repo.event(conn,execution['task_id'],'job_unit_waiting_resource',
                        {'job_id':execution['job_id'],'owner':kwargs['owner'],
                         'operation':kwargs['profile'].operation,'resource':exc.resource,
                         'seconds':exc.seconds,'new_paid_attempt':False})
                await asyncio.sleep(min(exc.seconds,30))
        self.save(execution, key, {"kind": "model", "response": response, "receipt": receipt,
            **({'bindings': bindings} if bindings is not None else {})})
        return response, receipt

    def http(self, execution):
        return JobHTTP(self, execution)


class JobHTTP:
    @property
    def endpoint_preferences(self):
        return self.steps.app.http.endpoint_preferences

    def __init__(self, steps, execution):
        self.steps, self.job = steps, execution

    async def request(self, task_id, owner, service, method, url, **kwargs):
        import asyncio
        recover_cache=kwargs.pop('recover_unavailable_cache',False)
        validator=kwargs.pop('_validate_response',None)
        identity = digest({'task': task_id, 'owner': owner, 'service': service,
                           'method': method, 'url': url,
                           'arguments': {k: v for k, v in kwargs.items() if k not in {'timeout', 'connect_timeout', 'read_timeout'}}})
        if not hasattr(self.steps.app.http, 'request_locks'):
            self.steps.app.http.request_locks = {}
        locks = self.steps.app.http.request_locks
        async with locks.setdefault(identity, asyncio.Lock()):
            from .run_policy import dispatch_remaining
            left = dispatch_remaining(self.steps.repo, self.job)
            if left is not None:
                kwargs['timeout'] = min(kwargs.get('timeout', 45), left)
            return await self._request(task_id, owner, service, method, url,
                                       recover_unavailable_cache=recover_cache, _validate_response=validator, **kwargs)

    async def _request(self, task_id, owner, service, method, url, **kwargs):
        recover_cache=kwargs.pop('recover_unavailable_cache',False)
        validator=kwargs.pop('_validate_response',None)
        protocol_errors={'SOURCE_PROTOCOL_UNAVAILABLE','CATALOG_NOT_FOUND','VOTABLE_PARSE_ERROR','CATALOG_SERVICE_ERROR'}
        invalid_cache=False
        if task_id != self.job["task_id"]:
            raise DomainError("STEP_TASK_MISMATCH", "作业步骤不属于该任务")
        if owner not in {'M01', 'M03', 'M04', 'M05', 'M06'}:
            raise DomainError('SOURCE_READ_FORBIDDEN', '该模块没有来源读取权限')
        # Headers are deliberately absent from persisted records. The key binds
        # their hash so a different credential/config cannot reuse a step.
        key = "step-" + digest(
            {
                "job": self.job["job_id"],
                "kind": "http",
                "owner": owner,
                "service": service,
                "method": method,
                "url": url,
                "arguments": kwargs,
            }
        )
        cache_key = 'http-response-' + digest({'owner': owner, 'service': service, 'method': method, 'url': url,
            'arguments': {k: v for k, v in kwargs.items() if k not in {'timeout', 'connect_timeout', 'read_timeout', 'max_bytes'}}})
        previous = self.steps.load(self.job, key)
        if previous:
            try:
                _, path = self.steps.app.artifacts.read_owned(
                    task_id, previous["artifact"]["artifact_id"])
                raw=path.read_bytes()
                if validator:validator(raw)
                return raw, previous["metadata"]
            except DomainError as exc:
                if not (validator and exc.code in protocol_errors) and (not recover_cache or exc.code not in {'ARTIFACT_MISSING','ARTIFACT_CORRUPT'}):raise
                invalid_cache=True
        if method.upper() == 'GET':
            with self.steps.repo.read() as conn:
                self.steps.repo.validate_lease(conn, self.job)
                try:
                    cached = self.steps.repo.object(conn, task_id, 'http_response_cache', cache_key)
                except DomainError as exc:
                    if exc.code != 'OBJECT_NOT_FOUND':
                        raise
                    cached = None
            if cached:
                try:
                    _, path = self.steps.app.artifacts.read_owned(task_id, cached['artifact']['artifact_id'])
                    raw = path.read_bytes()
                    if len(raw) <= kwargs.get('max_bytes', 16 * 1024**2):
                        if validator:validator(raw)
                        metadata = {**cached['metadata'], 'same_task_response_reuse': True}
                        body={'kind':'http','artifact':cached['artifact'],'metadata':metadata}
                        if invalid_cache:
                            with self.steps.repo.transaction() as conn:
                                self.steps.repo.validate_lease(conn,self.job,scientific=False)
                                self.steps.app.artifacts.register(conn,task_id,key,cached['artifact'])
                                version=conn.execute("select coalesce(max(version),0)+1 from objects where task_id=? and kind='job_step' and object_id=?",(task_id,key)).fetchone()[0]
                                self.steps.repo.put_object(conn,task_id,'job_step',key,version,body)
                        else:
                            self.steps.save(self.job,key,body,cached['artifact'])
                        return raw, metadata
                except DomainError as exc:
                    if exc.code not in {'ARTIFACT_NOT_FOUND', 'ARTIFACT_UNAVAILABLE'} and not (validator and exc.code in protocol_errors) and not (
                            recover_cache and exc.code in {'ARTIFACT_MISSING','ARTIFACT_CORRUPT'}):
                        raise
                    invalid_cache=True
        raw, metadata = await self.steps.app.http.request(
            task_id, owner, service, method, url, **kwargs
        )
        if validator:
            try:validator(raw)
            except DomainError as exc:
                artifact=self.steps.app.artifacts.write(raw,metadata.get('media_type') or 'application/octet-stream')
                with self.steps.repo.transaction() as conn:
                    self.steps.repo.validate_lease(conn,self.job,scientific=False)
                    identity='protocol-failure-'+digest([self.job['job_id'],metadata.get('attempt_id'),artifact['sha256']])
                    self.steps.app.artifacts.register(conn,task_id,identity,artifact)
                    self.steps.repo.put_object(conn,task_id,'http_protocol_failure',identity,1,
                        {'artifact':artifact,'metadata':metadata,'reason':exc.code,'success_cache_written':False})
                raise
        artifact = self.steps.app.artifacts.write(
            raw, metadata.get("media_type") or "application/octet-stream",
            repair_corrupt=recover_cache,
        )
        body={"kind":"http","artifact":artifact,"metadata":metadata}
        if invalid_cache:
            with self.steps.repo.transaction() as conn:
                self.steps.repo.validate_lease(conn,self.job,scientific=False)
                self.steps.app.artifacts.register(conn,task_id,key,artifact)
                version=conn.execute("select coalesce(max(version),0)+1 from objects where task_id=? and kind='job_step' and object_id=?",(task_id,key)).fetchone()[0]
                self.steps.repo.put_object(conn,task_id,'job_step',key,version,body)
                self.steps.repo.event(conn,task_id,'http_cache_restored',{'job_id':self.job['job_id'],'artifact_id':artifact['artifact_id'],'previous_versions_retained':True})
        else:
            self.steps.save(self.job,key,body,artifact)
        if method.upper() == 'GET' and metadata.get('status') == 200:
            with self.steps.repo.transaction() as conn:
                self.steps.repo.validate_lease(conn, self.job)
                old=conn.execute("select coalesce(max(version),0) from objects where task_id=? and kind='http_response_cache' and object_id=?",(task_id,cache_key)).fetchone()[0]
                if not old or invalid_cache:
                    self.steps.repo.put_object(conn, task_id, 'http_response_cache', cache_key, old+1,
                        {'cache_id': cache_key, 'artifact': artifact, 'metadata': metadata,
                         'scope': 'same_task_owner_request_and_credential_hash', 'fresh_network_response': False})
        return raw, metadata
