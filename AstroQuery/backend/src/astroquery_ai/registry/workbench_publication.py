"""Short SQLite publication transaction and verified immutable staging files."""
import os
import shutil
import sqlite3
from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads, new_id, utcnow
from astroquery_ai.runtime.errors import DomainError
from .workbench_projection import apply_operations
from .workspace_release import knowledge_compatibility


def prior_operation(conn, token, request):
    if not isinstance(token, str) or not token.strip() or len(token) > 200:
        raise DomainError('IDEMPOTENCY_REQUIRED', '需要有效幂等操作标识', 422)
    row = conn.execute('SELECT request_hash,response FROM registry_operations WHERE operation_id=?', (token,)).fetchone()
    if row:
        if row['request_hash'] != digest(request):
            raise DomainError('IDEMPOTENCY_CONFLICT', '同一操作标识不能用于不同请求', 409)
        return loads(row['response'])


def store_operation(conn, token, request, response):
    conn.execute('INSERT INTO registry_operations VALUES(?,?,?)', (token, digest(request), canonical(response)))


def set_active(conn, bundle):
    for setting, payload in [('active_bundle', bundle), ('active_registry', bundle['registry_ref']), ('active_knowledge', bundle.get('knowledge_ref'))]:
        if payload is None:
            conn.execute('DELETE FROM settings WHERE key=?', (setting,))
        else:
            if setting == 'active_registry':
                payload = {'release_id': payload['id'], 'content_sha256': payload['content_sha256']}
            conn.execute('INSERT INTO settings VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,revision=settings.revision+1', (setting, canonical(payload)))


def publish(bench, workspace_id, **arguments):
    request = {'action': 'publish', 'workspace_id': workspace_id, **arguments}
    token = arguments['idempotency_key']
    with bench.repository.read() as conn:
        previous = prior_operation(conn, token, request)
        if previous:
            return previous
    workspace = bench.get_workspace(workspace_id); bench._revision(workspace, arguments['expected_revision'])
    validation = workspace.get('validation')
    if not validation or validation['id'] != arguments['validation_id'] or validation['workspace_revision'] != workspace['revision'] or validation['state'] != 'passed':
        raise DomainError('VALIDATION_REQUIRED', '发布需要当前草稿通过的校验', 409)
    release, base = bench._base(workspace['base_bundle']['registry_ref'])
    projection = apply_operations(base, workspace['operations'])
    if digest(projection) != validation['projection_sha256']:
        raise DomainError('VALIDATION_STALE', '校验依据已改变', 409)
    from .user_execution import compile_execution
    execution, _, execution_errors = compile_execution(projection, release)
    if execution_errors or execution != validation.get('execution', {}).get('manifest'):
        raise DomainError('VALIDATION_STALE', 'Execution validation changed', 409)
    registry_id = 'registry_workspace_' + new_id()
    base_knowledge_ref = workspace['base_bundle'].get('knowledge_ref')
    base_knowledge = bench.knowledge.load(base_knowledge_ref) if base_knowledge_ref and bench.knowledge else None
    if base_knowledge_ref and not bench.knowledge:
        raise DomainError('KNOWLEDGE_SERVICE_REQUIRED', '发布缺少知识兼容性验证服务', 503)
    compatibility = knowledge_compatibility(base_knowledge, projection)
    payload = {'schema_version': 'registry-workspace/1', 'workspace_id': workspace_id,
        'workspace_revision': workspace['revision'], 'base_registry_ref': workspace['base_bundle']['registry_ref'],
        'base_knowledge_ref': base_knowledge_ref, 'projection': projection, 'execution_manifest': execution,
        'capability_compatibility': {'policy': 'exact-unchanged-scopes-only/1', 'scientific_review_granted': False,
            'model_qualification_granted': False, 'compatible_property_keys': [p['id'] for p in projection['properties'].values() if p.get('automatic_conversion_ready')],
            'gaps': [p['id'] for p in projection['properties'].values() if not p.get('automatic_conversion_ready')]}}
    manifest = {'schema_version': 'registry-workspace/1', 'release_id': registry_id, 'status': 'local_published',
        'synthetic': release['manifest'].get('synthetic', False), 'workspace_sha256': digest(payload)}
    manifest['content_sha256'] = content_hash(manifest)
    registry_ref = {'id': registry_id, 'version': 1, 'content_sha256': manifest['content_sha256']}
    destinations = []; stages = []
    parent = bench.registry.root / 'releases'; parent.mkdir(parents=True, exist_ok=True)
    stage = parent / ('.workspace-' + new_id()); destination = parent / registry_id
    try:
        stage.mkdir(); stages.append(stage)
        (stage / 'workspace.json').write_bytes(canonical(payload)); (stage / 'manifest.json').write_bytes(canonical(manifest))
        verified_registry = bench.registry.validate(stage)
        destinations.append((stage, destination, registry_ref, 'property'))
        knowledge_ref = None
        if base_knowledge:
            knowledge_id = 'knowledge_workspace_' + new_id()
            knowledge_payload = {'schema_version': 'insight-knowledge-workspace/1', 'base_knowledge_ref': base_knowledge_ref,
                'compatibility_policy': 'cumulative-exact-source/2',
                'compatible_binding_ids': compatibility['compatible_binding_ids'], 'gaps': compatibility['gaps'],
                'original_author_content_unchanged': True}
            knowledge_manifest = {'schema_version': 'insight-knowledge-workspace/1', 'release_id': knowledge_id,
                'status': 'local_published', 'synthetic': manifest['synthetic'], 'registry_release_ref': registry_ref,
                'base_knowledge_ref': base_knowledge_ref, 'compatibility_sha256': digest(knowledge_payload)}
            knowledge_manifest['content_sha256'] = content_hash(knowledge_manifest)
            knowledge_ref = {'id': knowledge_id, 'version': 1, 'content_sha256': knowledge_manifest['content_sha256']}
            kparent = bench.knowledge.root / 'releases'; kparent.mkdir(parents=True, exist_ok=True)
            kstage = kparent / ('.workspace-' + new_id()); kstage.mkdir(); stages.append(kstage)
            (kstage / 'compatibility.json').write_bytes(canonical(knowledge_payload)); (kstage / 'manifest.json').write_bytes(canonical(knowledge_manifest))
            from types import SimpleNamespace
            from .workspace_release import load_workspace_knowledge
            staged_service = SimpleNamespace(load=bench.knowledge.load,
                registry=SimpleNamespace(load=lambda identifier: verified_registry if identifier == registry_id else bench.registry.load(identifier)))
            load_workspace_knowledge(staged_service, kstage, knowledge_manifest)
            destinations.append((kstage, kparent / knowledge_id, knowledge_ref, 'knowledge'))
        with bench.repository.transaction() as conn:
            previous = prior_operation(conn, token, request)
            if previous:
                return previous
            current = bench._workspace(conn, workspace_id); bench._revision(current, arguments['expected_revision'])
            if current.get('validation') != validation:
                raise DomainError('VALIDATION_STALE', '校验依据已改变', 409)
            active = bench.registry.active_bundle(conn)
            if active['id'] != arguments['expected_active_bundle_id']:
                raise DomainError('ACTIVE_BUNDLE_CONFLICT', '当前启用版本已改变', 409)
            bundle = {'id': 'bundle_' + digest({'registry_ref': registry_ref, 'knowledge_ref': knowledge_ref}),
                'revision': active['revision'] + 1, 'registry_ref': registry_ref, 'knowledge_ref': knowledge_ref,
                'base_bundle_id': workspace['base_bundle']['id'], 'capability_ref': {'id': 'capability_' + digest(payload['capability_compatibility']),
                    'version': 1, 'content_sha256': digest(payload['capability_compatibility'])}}
            for staged, target, reference, kind in destinations:
                os.replace(staged, target)
                conn.execute('INSERT INTO registry_releases VALUES(?,?,?,?,?,?)',
                    (reference['id'], reference['content_sha256'], str(target), kind, int(manifest['synthetic']), utcnow()))
            current['status'] = 'published'; current['release_id'] = registry_id; current['bundle_id'] = bundle['id']
            bench._save(conn, current)
            conn.execute('INSERT OR IGNORE INTO registry_bundles VALUES(?,?,?)', (active['id'], canonical(active), utcnow()))
            conn.execute('INSERT INTO registry_bundles VALUES(?,?,?)', (bundle['id'], canonical(bundle), utcnow()))
            set_active(conn, bundle)
            response = {'success': True, 'release': {'id': registry_id, 'release_id': registry_id, 'content_sha256': manifest['content_sha256']},
                'bundle': bundle, 'workspace': {k: current[k] for k in ('id', 'revision', 'status')}}
            store_operation(conn, token, request, response)
        return response
    except (OSError, sqlite3.Error) as exc:
        raise DomainError('WORKSPACE_PUBLICATION_FAILED', '发布持久化失败，启用版本未改变', 503) from exc
    finally:
        # Only private stages in verified release directories are removed. A
        # renamed orphan on failed commit is unreachable and retained for audit.
        for staged in stages:
            if staged.exists() and staged.name.startswith('.workspace-') and staged.resolve().parent in {bench.registry.root.resolve() / 'releases', bench.knowledge.root.resolve() / 'releases' if bench.knowledge else bench.registry.root.resolve() / 'releases'}:
                shutil.rmtree(staged)


def activate(bench, release_id, *, expected_active_bundle_id, idempotency_key):
    request = {'action': 'activate', 'release_id': release_id, 'expected_active_bundle_id': expected_active_bundle_id, 'idempotency_key': idempotency_key}
    try:
        with bench.repository.transaction() as conn:
            previous = prior_operation(conn, idempotency_key, request)
            if previous:
                return previous
            rows = [loads(r[0]) for r in conn.execute('SELECT payload FROM registry_bundles')]
            bundle = next((b for b in rows if b['id'] == release_id or b['registry_ref']['id'] == release_id), None)
            if not bundle:
                raise DomainError('BUNDLE_NOT_FOUND', '发布版本组合不存在', 404)
            active = bench.registry.active_bundle(conn)
            if active['id'] != expected_active_bundle_id:
                raise DomainError('ACTIVE_BUNDLE_CONFLICT', '当前启用版本已改变', 409)
            bench._base(bundle['registry_ref'])
            if bundle.get('knowledge_ref') and bench.knowledge:
                knowledge = bench.knowledge.load(bundle['knowledge_ref'])
                if (knowledge['manifest']['content_sha256'] != bundle['knowledge_ref']['content_sha256']
                        or knowledge['manifest']['registry_release_ref'] != bundle['registry_ref']):
                    raise DomainError('KB_BASE_CHANGED', '知识版本内容不匹配', 422)
            bundle = {**bundle, 'revision': active['revision'] + 1}
            set_active(conn, bundle)
            response = {'success': True, 'bundle': bundle}
            store_operation(conn, idempotency_key, request, response)
        return response
    except (OSError, sqlite3.Error) as exc:
        raise DomainError('WORKSPACE_ACTIVATION_FAILED', '版本切换持久化失败', 503) from exc
