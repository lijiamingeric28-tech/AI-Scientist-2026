"""Synthetic protocol/accounting regressions, not scientific acceptance claims."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from astroquery_ai.runtime.budget import Budget, price_for
from astroquery_ai.runtime.cache_pricing import reservation_cost, usage_estimate
from astroquery_ai.runtime.calls import ModelGateway, ModelProfile
from astroquery_ai.runtime.checkpoints import JobSteps
from astroquery_ai.runtime.codec import canonical, loads
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.prompt_cache import PromptCache, ordered_prompt, public_metadata
from astroquery_ai.runtime.provider import BEIJING
from astroquery_ai.runtime.repository import Repository

VALUES = {'dashscope_base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
          'dashscope_api_key': 'SYNTHETIC-NOT-A-KEY'}
PROFILE = ModelProfile(model='qwen3.7-plus', version='synthetic-cache', operation='paper_admission')


def messages(value='1.02', rule='SYNTHETIC JSON object ' * 600):
    body = {'candidates': [{'value': value, 'error': '0.05', 'unit': 'mag'}],
            'target': {'main_id': 'SYNTHETIC', 'aliases': ['x', 'y']},
            'schema': {'properties': {'items': {'type': 'array'}}},
            'instruction': rule, 'source_blocks': [{'text': '原文 λ > 3000 Å; ± "quote"'}]}
    return [{'role': 'user', 'content': [{'type': 'text', 'text': canonical(body).decode()},
            {'type': 'text', 'text': 'CORE PDF page 2'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,SYNTHETIC'}}]},
            {'role': 'user', 'content': 'SYNTHETIC repair feedback, unchanged'}]


def first_object(wire):
    if 'cache_control' in wire[0]['content'][0]:
        value = loads(wire[0]['content'][0]['text'])
        tail = wire[1]['content']
        tail = tail if isinstance(tail, str) else tail[0]['text']
        variable = loads(tail)
        assert not set(value) & set(variable)
        return {**value, **variable}
    return loads(wire[0]['content'][0]['text'])


def test_wire_reordering_is_lossless_and_does_not_mutate_or_renumber_evidence(monkeypatch):
    monkeypatch.setenv('ASTROQUERY_PROMPT_CACHE_MODE', 'implicit')
    original = messages()
    before = canonical(original)
    cache = PromptCache()
    wire, meta = cache.prepare(original, task_id='one', profile=PROFILE, values=VALUES)
    assert first_object(wire) == loads(original[0]['content'][0]['text'])
    assert list(first_object(wire))[:2] == ['schema', 'instruction']
    assert wire[0]['content'][1:] == original[0]['content'][1:]
    assert wire[1:] == original[1:] and canonical(original) == before
    other, second = cache.prepare(messages('28.09'), task_id='one', profile=PROFILE, values=VALUES)
    assert meta['prefix_sha256'] == second['prefix_sha256']
    assert first_object(other)['candidates'][0]['value'] == '28.09'
    _, changed = cache.prepare(messages(rule='different rule ' * 900), task_id='one', profile=PROFILE, values=VALUES)
    assert changed['prefix_sha256'] != meta['prefix_sha256']
    changed_scope = messages()
    scoped = loads(changed_scope[0]['content'][0]['text'])
    scoped['target']['main_id'] = 'SYNTHETIC-DIFFERENT-TARGET'
    changed_scope[0]['content'][0]['text'] = canonical(scoped).decode()
    _, scope_meta = cache.prepare(changed_scope, task_id='one', profile=PROFILE, values=VALUES)
    assert scope_meta['prefix_sha256'] != meta['prefix_sha256']
    assert 'SYNTHETIC-NOT-A-KEY' not in str(public_metadata(meta))


def test_explicit_auto_waits_for_observed_low_hits_without_paid_warmup_or_wait(monkeypatch):
    monkeypatch.setenv('ASTROQUERY_PROMPT_CACHE_MODE', 'auto')
    clock = [1.0]
    cache = PromptCache(clock=lambda: clock[0])
    usage = {'prompt_tokens': 5000, 'prompt_tokens_details': {'cached_tokens': 0}}
    for _ in range(2):
        _, meta = cache.prepare(messages(), task_id='one', profile=PROFILE, values=VALUES, future_calls=3)
        assert meta['mode'] == 'implicit'
        cache.observe(meta, usage, success=True)
    _, few = cache.prepare(messages(), task_id='one', profile=PROFILE, values=VALUES, future_calls=1)
    assert few['mode'] == 'implicit'
    wire, creating = cache.prepare(messages(), task_id='one', profile=PROFILE, values=VALUES, future_calls=2)
    assert creating['mode'] == 'explicit' and first_object(wire) == first_object(messages())
    assert wire[1]['content'][1:] == messages()[0]['content'][1:]
    assert wire[0]['role'] == wire[1]['role'] == messages()[0]['role']
    assert wire[2:] == messages()[1:]
    _, sibling = cache.prepare(messages('28.09'), task_id='one', profile=PROFILE, values=VALUES, future_calls=3)
    assert sibling['mode'] == 'implicit'
    cache.observe(sibling, usage, success=True)  # Must not release another call's creation lease.
    assert cache.prepare(messages(), task_id='one', profile=PROFILE, values=VALUES, future_calls=3)[1]['mode'] == 'implicit'
    cache.observe(creating, {'prompt_tokens': 5000, 'prompt_tokens_details':
        {'cached_tokens': 0, 'cache_creation_input_tokens': 3000}}, success=True)
    assert cache.prepare(messages(), task_id='one', profile=PROFILE, values=VALUES)[1]['mode'] == 'explicit'
    assert cache.prepare(messages(), task_id='different-query', profile=PROFILE, values=VALUES, future_calls=3)[1]['mode'] == 'implicit'
    clock[0] += 301
    assert cache.prepare(messages(), task_id='one', profile=PROFILE, values=VALUES, future_calls=3)[1]['mode'] == 'implicit'


def test_explicit_rollback_and_unsupported_provider_or_prefix(monkeypatch):
    monkeypatch.setenv('ASTROQUERY_PROMPT_CACHE_MODE', 'explicit')
    cache = PromptCache()
    kwargs = dict(task_id='one', profile=PROFILE, values=VALUES)
    _, meta = cache.prepare(messages(), **kwargs)
    cache.observe(meta, None, success=False, rejected=True)
    assert cache.prepare(messages(), **kwargs)[1]['mode'] == 'implicit'
    assert cache.prepare(messages(), **{**kwargs, 'values': {**VALUES, 'dashscope_base_url': 'https://example.test/v1'}})[1]['mode'] == 'implicit'
    assert cache.prepare(messages(rule='JSON'), **kwargs)[1]['mode'] == 'implicit'
    unchanged = messages()
    monkeypatch.setenv('ASTROQUERY_PROMPT_CACHE_MODE', 'off')
    assert cache.prepare(unchanged, **kwargs)[0] is unchanged
    assert ordered_prompt('{"schema":{},"value":1,"value":2}') is None


def test_explicit_boundary_has_an_accurate_input_reservation_and_falls_back_without_room(monkeypatch):
    from astroquery_ai.runtime.calls import input_upper_bound
    monkeypatch.setenv('ASTROQUERY_PROMPT_CACHE_MODE', 'explicit')
    original = [{'role':'user','content':messages()[0]['content'][0]['text']}]
    kwargs = dict(task_id='one', profile=PROFILE, values=VALUES)
    wire, meta = PromptCache().prepare(original, **kwargs)
    assert meta['mode'] == 'explicit'
    assert input_upper_bound(wire) == input_upper_bound(original) + 65
    fallback, meta = PromptCache().prepare(original, **kwargs, allow_explicit=False)
    assert meta['mode'] == 'implicit' and isinstance(fallback[0]['content'], str)
    assert loads(fallback[0]['content']) == loads(original[0]['content'])


def test_auto_keeps_longer_implicit_hits_when_they_are_cheaper_than_explicit(monkeypatch):
    monkeypatch.setenv('ASTROQUERY_PROMPT_CACHE_MODE', 'auto')
    cache = PromptCache()
    kwargs = dict(task_id='one',profile=replace(PROFILE,model='qwen3.8-flash'),values=VALUES,future_calls=10)
    for _ in range(2):
        _, meta = cache.prepare(messages(), **kwargs)
        cache.observe(meta, {'prompt_tokens':30000,'prompt_tokens_details':{'cached_tokens':10000}}, success=True)
    _, probe = cache.prepare(messages(), **kwargs)
    assert probe['mode'] == 'explicit'
    cache.observe(probe, {'prompt_tokens':30000,'prompt_tokens_details':
        {'cached_tokens':0,'cache_creation_input_tokens':7000}}, success=True)
    _, next_call = cache.prepare(messages(), **kwargs)
    assert next_call['mode'] == 'implicit' and next_call['explicit_expected_cheaper'] is False
    # Plus reads have a larger explicit discount; compare prices, not just tokens.
    cache = PromptCache();kwargs['profile'] = PROFILE
    for _ in range(2):
        _, meta = cache.prepare(messages(), **kwargs)
        cache.observe(meta, {'prompt_tokens':20000,'prompt_tokens_details':{'cached_tokens':6000}}, success=True)
    _, probe = cache.prepare(messages(), **kwargs)
    cache.observe(probe, {'prompt_tokens':20000,'prompt_tokens_details':
        {'cached_tokens':0,'cache_creation_input_tokens':6000}}, success=True)
    assert cache.prepare(messages(), **kwargs)[1]['mode'] == 'explicit'


def test_missing_implicit_hit_usage_is_not_evidence_for_a_paid_cache_probe(monkeypatch):
    monkeypatch.setenv('ASTROQUERY_PROMPT_CACHE_MODE', 'auto')
    cache = PromptCache()
    kwargs = dict(task_id='one',profile=PROFILE,values=VALUES,future_calls=10)
    for details in ({}, {'cached_tokens':-1}, {'cached_tokens':True}, {'cached_tokens':10001}):
        _, meta = cache.prepare(messages(), **kwargs)
        cache.observe(meta, {'prompt_tokens':10000,'prompt_tokens_details':details}, success=True)
    assert cache.prepare(messages(), **kwargs)[1]['mode'] == 'implicit'


@pytest.mark.parametrize('model,read,create', [('qwen3.8-flash', 10, 125), ('qwen3.7-plus', 20, 250), ('qwen3.8-max', 100, 1500)])
def test_cache_cost_includes_creation_premium_and_counts_reasoning_only_once(model, read, create):
    receipt = {'provider_identity': BEIJING, 'prompt_cache': {'mode': 'explicit'}, 'usage':
        {'prompt_tokens': 10000, 'completion_tokens': 100, 'completion_tokens_details': {'reasoning_tokens': 80},
         'prompt_tokens_details': {'cached_tokens': 6000, 'cache_creation_input_tokens': 2000}}}
    estimate = usage_estimate(model, 10000, 100, receipt)
    out = {'qwen3.8-flash': 270, 'qwen3.7-plus': 800, 'qwen3.8-max': 3600}[model]
    ordinary = {'qwen3.8-flash': 80, 'qwen3.7-plus': 200, 'qwen3.8-max': 1200}[model]
    assert estimate['estimated_micros'] == (2000*ordinary + 6000*read + 2000*create + 100*out + 99)//100
    assert estimate['reasoning_tokens'] == 80
    request = {'messages': [{'content': [{'type': 'text', 'text': 'SYNTHETIC', 'cache_control': {'type': 'ephemeral'}}]}]}
    assert reservation_cost(model, 10000, 100, request) == (10000*create + 100*out + 99)//100


def test_unknown_cache_usage_is_conservative_and_custom_endpoints_get_no_assumed_discount():
    for details in ({}, None, [], {'cached_tokens': 20000}, {'cached_tokens': 9000}, {'cached_tokens': True}):
        r = {'provider_identity': BEIJING, 'prompt_cache': {'mode': 'explicit'},
             'usage': {'prompt_tokens_details': details}}
        e = usage_estimate('qwen3.8-flash', 10000, 100, r)
        assert not e['cache_usage_known'] and e['estimated_micros'] >= e['list_price_micros']
    receipt = {'usage': {'prompt_tokens_details': {'cached_tokens': 9000}}}
    assert usage_estimate('qwen3.8-flash', 10000, 100, receipt)['estimated_micros'] == price_for('qwen3.8-flash', 10000).cost(10000, 100)


def test_failed_output_stays_rejected_but_its_cache_usage_is_persisted(tmp_path):
    from tests.rebuild.test_provider_and_delivery import gateway, call
    usage = {'prompt_tokens': 100, 'completion_tokens': 20, 'prompt_tokens_details': {'cached_tokens': 80}}
    raw = '[{"value":"1.02"}]'  # JSON-mode must still reject a root array.
    chunks = [{'choices': [{'delta': {'content': raw}, 'finish_reason': 'stop'}]}, {'choices': [], 'usage': usage}]
    stream = ''.join('data: ' + canonical(c).decode() + '\n\n' for c in chunks) + 'data: [DONE]\n\n'
    model, budget, task, captured = gateway(tmp_path, stream)
    model.config.runtime.update(VALUES)  # Mock transport only; no network.
    with pytest.raises(DomainError) as exc:
        call(model, task)
    assert exc.value.code == 'INVALID_MODEL_JSON' and len(captured) == 1
    with budget.repository.read() as conn:
        row = conn.execute('select receipt,actual_micros from attempts').fetchone()
        receipt = loads(row[0])
        assert receipt['usage'] == usage and receipt['cost_estimate']['cached_input_tokens'] == 80
        assert not budget.repository.objects(conn, task['task_id'], 'model_success')
        assert not budget.repository.objects(conn, task['task_id'], 'measurement')


def step_app(tmp_path):
    repo = Repository(tmp_path/'steps.sqlite3')
    task = repo.create_task('SYNTHETIC paid-step recovery')
    budget = Budget(repo)
    with repo.transaction() as conn:
        repo.enqueue(conn, task['task_id'], 'M06', 'synthetic_step', {})
        repo.enqueue(conn, task['task_id'], 'M06', 'synthetic_step', {'independent': True})
        # Synthetic leased-job/calibration seam only, not a production query.
        conn.execute('update tasks set kind=\'validation\' where task_id=?', (task['task_id'],))
    job = repo.claim_job('test', task_id=task['task_id'])
    count = []
    usage = {'prompt_tokens': 10, 'completion_tokens': 2}
    stream = 'data: '+canonical({'choices':[{'delta':{'content':'{"ok":true}'},'finish_reason':'stop'}], 'usage':usage}).decode()+'\n\ndata: [DONE]\n\n'
    def handle(request):
        count.append(1)
        return httpx.Response(200, content=stream, headers={'content-type':'text/event-stream'})
    app = SimpleNamespace(repository=repo)
    app.models = ModelGateway(SimpleNamespace(runtime=VALUES), budget, transport=httpx.MockTransport(handle))
    return app, budget, task, job, count


def test_identical_concurrent_job_steps_pay_once_and_crash_after_settlement_recovers(tmp_path, monkeypatch):
    app, budget, task, job, count = step_app(tmp_path)
    steps = JobSteps(app)
    kwargs = dict(task_id=task['task_id'], owner='M06', root_id='same', messages=[{'role':'user','content':'SYNTHETIC JSON'}],
                  profile=replace(PROFILE, model='qwen3.8-flash', thinking=False), job=job, smoke=True)
    save = steps.save
    def interrupted(*args, **kwargs):
        raise RuntimeError('SYNTHETIC process death after paid response')
    monkeypatch.setattr(steps, 'save', interrupted)
    with pytest.raises(RuntimeError):
        asyncio.run(steps.model(job, **kwargs))
    assert len(count) == 1
    monkeypatch.setattr(steps, 'save', save)
    async def resume():
        return await asyncio.gather(steps.model(job, **kwargs), steps.model(job, **kwargs))
    results = asyncio.run(resume())
    assert results[0][0] == results[1][0] == {'ok': True} and len(count) == 1
    assert not app._model_step_locks
    with app.repository.read() as conn:
        assert conn.execute('select count(*) from attempts').fetchone()[0] == 1
        assert len(app.repository.objects(conn, task['task_id'], 'model_success')) == 1


def test_identical_inflight_job_steps_share_one_response_without_merging_independent_jobs(tmp_path):
    app, budget, task, job, count = step_app(tmp_path)
    transport = app.models.transport
    async def delayed(request):
        await asyncio.sleep(.03)
        return transport.handle_request(request)
    app.models.transport = httpx.MockTransport(delayed)
    steps = JobSteps(app)
    kwargs = dict(task_id=task['task_id'],owner='M06',root_id='same',messages=[{'role':'user','content':'SYNTHETIC JSON'}],
        profile=replace(PROFILE,model='qwen3.8-flash',thinking=False),job=job,smoke=True)
    async def run():
        return await asyncio.gather(*(steps.model(job, **kwargs) for _ in range(4)))
    results = asyncio.run(run())
    assert len(count) == 1 and len(results) == 4


def test_same_prompt_different_jobs_and_changed_feedback_remain_independent(tmp_path, monkeypatch):
    app, budget, task, job, count = step_app(tmp_path)
    # Avoid rate waits in this synthetic independence test only.
    app.models.traffic.rpm = 100000
    app.models.traffic.tpm = 10**12
    steps = JobSteps(app)
    kwargs = dict(task_id=task['task_id'], owner='M06', root_id='same', messages=[{'role':'user','content':'SYNTHETIC JSON'}],
                  profile=replace(PROFILE, model='qwen3.8-flash', thinking=False), job=job, smoke=True)
    async def run():
        await steps.model(job, **kwargs)
        await steps.model(job, **{**kwargs, 'messages': [*kwargs['messages'], {'role':'user','content':'SYNTHETIC changed feedback'}]})
        with app.repository.transaction() as conn:
            app.repository.finish_job(conn, job)
        second = app.repository.claim_job('test', task_id=task['task_id'])
        await steps.model(second, **{**kwargs, 'job':second})
    asyncio.run(run())
    assert len(count) == 3
