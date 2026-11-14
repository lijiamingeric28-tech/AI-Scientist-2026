"""Report recheck is not permission to reopen sealed science."""
from copy import deepcopy

import pytest

from astroquery_ai.runtime.codec import canonical, digest
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.report_recheck import allowed


def setup_scope(tmp_path):
    repo = Repository(tmp_path / 'runtime.sqlite3')
    tid = repo.create_task('SYNTHETIC read-only owner scope')['task_id']
    request = {'model': 'qwen3.7-plus', 'enable_thinking': False, 'max_tokens': 8192,
               'messages': [{'role': 'user', 'content': 'SYNTHETIC JSON original material'}]}
    record = {'measurement_id': 'record', 'revision': 1, 'content_sha256': 'record-hash',
              'property_ref': {'id': 'property'}, 'source_ref': {'id': 'source'}}
    delivery = {'delivery_id': 'delivery', 'snapshot_ref': {'id': 'snapshot', 'version': 1, 'content_sha256': 'snapshot-hash'},
                'measurements': [record], 'sources': [{'source_id': 'source', 'kind': 'paper'}]}
    with repo.transaction() as c:
        spec = repo.put_object(c, tid, 'confirmed_query', 'query', 1,
                              {'run_policy': {'insights': {'presentation': 'research-property/1'}}})
        repo.put_object(c, tid, 'delivery', 'delivery', 1, delivery)
        jid = repo.enqueue(c, tid, 'M11', 'insights', {'delivery_id': 'delivery'})
        repo.mutate_task(c, tid, query_ref=canonical(spec).decode(), science_state='sealed',
                         lifecycle='running', phase='insight')
        scope = {'job_id': jid, 'root_id': 'exact-root', 'delivery_id': 'delivery',
                 'snapshot_ref': delivery['snapshot_ref'], 'property_id': 'property', 'source_id': 'source',
                 'finding_ids': ['finding'], 'purpose': 'read_only_source_owner_recheck',
                 'measurement_refs': [{'id': 'record', 'version': 1, 'content_sha256': 'record-hash'}],
                 'messages_sha256': digest(request['messages'])}
        repo.put_object(c, tid, 'insight_owner_recheck_request', 'scope', 1, scope)
    job = {'job_id': jid, 'task_id': tid, 'kind': 'insights', 'payload': {'delivery_id': 'delivery'}}
    return repo, tid, job, request, scope


def test_exact_frozen_read_only_scope_can_use_responsible_owner(tmp_path):
    repo, tid, job, request, scope = setup_scope(tmp_path)
    with repo.read() as c:
        task = repo.task(c, tid)
        assert allowed(repo, c, task, 'M06', job, request, 'exact-root', 2) == scope
        assert repo.object(c, tid, 'delivery', 'delivery')['measurements'][0]['content_sha256'] == 'record-hash'


@pytest.mark.parametrize('change', ['owner', 'root', 'messages', 'model', 'attempts', 'job_kind', 'delivery', 'output'])
def test_unbound_or_broadened_scopes_do_not_unlock_sealed_processing(tmp_path, change):
    repo, tid, job, request, _ = setup_scope(tmp_path)
    request = deepcopy(request); job = deepcopy(job); owner = 'M06'; root = 'exact-root'; limit = 2
    if change == 'owner': owner = 'M08'
    if change == 'root': root = 'another-root'
    if change == 'messages': request['messages'][0]['content'] = 'not the scoped material'
    if change == 'model': request['model'] = 'qwen3.8-max'
    if change == 'attempts': limit = 3
    if change == 'job_kind': job['kind'] = 'paper_batch'
    if change == 'delivery': job['payload']['delivery_id'] = 'other-delivery'
    if change == 'output': request['max_tokens'] = 20000
    with repo.read() as c:
        assert allowed(repo, c, repo.task(c, tid), owner, job, request, root, limit) is None


def test_source_or_measurement_revision_mismatch_is_not_read_only_authority(tmp_path):
    repo, tid, job, request, scope = setup_scope(tmp_path)
    with repo.transaction() as c:
        scope['measurement_refs'][0]['content_sha256'] = 'other-record-hash'
        repo.put_object(c, tid, 'insight_owner_recheck_request', 'scope', 2, scope)
    with repo.read() as c:
        assert allowed(repo, c, repo.task(c, tid), 'M06', job, request, 'exact-root', 2) is None
