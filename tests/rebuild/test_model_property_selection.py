"""Synthetic protocol tests; these do not qualify real model semantics."""
import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.codec import digest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.query.selection import resolve_property_requests, resolve_explicit_selection
from astroquery_ai.query.semantic_selection import checked_selection


def binding(pid='synthetic-cycle'):
    return {'property_id': pid, 'definition': {'name_cn': 'SYNTHETIC规范名', 'name_en': 'SYNTHETIC canonical',
        'aliases': ['SYNTHETIC alias'], 'description': 'SYNTHETIC physical definition'},
        'output_profile': {'unit': 's'}, 'dependency_refs': []}


def answer(text, pid='synthetic-cycle', coverage='complete', related=False):
    return {'property_operation': 'replace', 'clarification_needed': False,
        'requests': [{'text': text, 'start': 0, 'end': len(text), 'coverage': coverage,
            'gap': '' if coverage == 'complete' else 'SYNTHETIC uncovered request',
            'candidates': [] if coverage == 'none' else [{'property_id': pid,
                'match': 'related' if related else 'equivalent', 'explanation': 'SYNTHETIC semantic explanation'}]}],
        'conditions': [], 'unknown_fragments': []}


def fake_draft():
    return {'property_support': {'bindings': [binding(), binding('synthetic-other')], 'support_hash': 'synthetic-hash'},
        'target': {'target_id': 'synthetic-target'}, 'selected_property_ids': [], 'issues': [], 'property_requests': []}


def test_empty_batch_gaps_do_not_require_duplicate_explanation_or_grant_properties():
    response = {'property_operation': 'replace', 'conditions': [], 'unknown_fragments': [],
        'requests': [{'text': 'SYNTHETIC unavailable in this batch', 'coverage': 'none',
                      'gap': 'SYNTHETIC missing from this batch',
                      'candidate_property_ids': [], 'equivalent_property_ids': []}]}
    checked, repairs = checked_selection(response, '', fake_draft()['property_support']['bindings'])
    assert checked['clarification_needed'] is False
    assert checked['requests'][0]['coverage'] == 'none'
    assert checked['requests'][0]['gap'] == response['requests'][0]['gap']
    assert checked['requests'][0]['candidates'] == []
    assert {r['field'] for r in repairs} == {'clarification_needed', 'explanation'}
    assert 'clarification_needed' not in response  # Saved model output is immutable.


def test_empty_gap_uses_existing_none_explanation_but_never_invents_evidence():
    response = {'property_operation': 'replace', 'clarification_needed': False,
        'conditions': [], 'unknown_fragments': [], 'requests': [{'text': 'SYNTHETIC request',
            'coverage': 'none', 'gap': '', 'explanation': 'SYNTHETIC no matching definition in this batch',
            'candidate_property_ids': [], 'equivalent_property_ids': []}]}
    checked, _ = checked_selection(response, '', fake_draft()['property_support']['bindings'])
    assert checked['requests'][0]['gap'] == response['requests'][0]['explanation']
    response['requests'][0]['explanation'] = ''
    with pytest.raises(DomainError):
        checked_selection(response, '', fake_draft()['property_support']['bindings'])


def test_nonempty_selection_still_requires_explicit_flag_and_candidate_scope():
    response = answer('SYNTHETIC request')
    del response['clarification_needed']
    with pytest.raises(DomainError):
        checked_selection(response, '', fake_draft()['property_support']['bindings'])
    response['clarification_needed'] = False
    response['requests'][0]['candidates'][0]['property_id'] = 'not-in-registry'
    with pytest.raises(DomainError):
        checked_selection(response, '', fake_draft()['property_support']['bindings'])


def test_literal_name_does_not_grant_a_property_without_model_answer():
    draft = fake_draft()
    with pytest.raises(DomainError, match='模型'):
        resolve_property_requests(draft, {'property_operation': 'replace'}, 'synthetic-op')
    assert not draft['selected_property_ids']


def test_candidate_ids_are_validated_and_related_is_not_silently_equivalent():
    draft = fake_draft()
    with pytest.raises(DomainError):
        checked_selection(answer('SYNTHETIC wording', 'not-registered'), 'SYNTHETIC wording', draft['property_support']['bindings'])
    semantic, _ = checked_selection(answer('SYNTHETIC wording', coverage='partial', related=True),
        'SYNTHETIC wording', draft['property_support']['bindings'])
    resolve_property_requests(draft, {}, 'synthetic-op', source_text='SYNTHETIC wording', semantic=semantic)
    assert not draft['selected_property_ids']
    assert any(i['kind'] == 'ambiguous_property' for i in draft['issues'])
    resolve_explicit_selection(draft, ['synthetic-cycle'], 'synthetic-choice')
    assert any(i.get('requires_omission') and i['status'] == 'open' for i in draft['issues'])


@pytest.mark.parametrize('wording', ['SYNTHETIC规范名', 'SYNTHETIC alias', 'SYNTHETIC转一圈多久'])
@pytest.mark.parametrize('release_version,expected_strategy',[
    ('retrieval-release/1',{'P':'P0','S':'S2','F':'F1','D':'D1'}),
    ('retrieval-feedback/1',{'P':'shared-feedback','S':'feedback-pages','F':'grounded-possible','D':'D1'}),
])
def test_normal_draft_runs_model_selection_even_for_canonical_name_and_alias(tmp_path, monkeypatch, wording,release_version,expected_strategy):
    app = Application(tmp_path)
    app.configuration.runtime['retrieval_policy_version']=release_version
    app.configuration.runtime.pop('research_delivery_version',None)
    release = {'manifest': {'release_id': 'synthetic-release', 'content_sha256': 'synthetic-release-hash'},
        'data': {'type-profiles': [{'otype': 'synthetic-type', 'subject_class_id': 'synthetic-subject'}]}}
    monkeypatch.setattr(app.registry, 'load', lambda *args: release)
    monkeypatch.setattr(app.registry, 'support', lambda *args: deepcopy(fake_draft()['property_support']))
    # This request-selection test uses an explicit synthetic installed release;
    # new normal confirmation also pins the active author knowledge version.
    monkeypatch.setattr(app.knowledge, 'load', lambda *args: {'manifest':{
        'schema_version':'insight-knowledge/3','release_id':'synthetic-author','content_sha256':'a'*64,
        'registry_release_ref': {'id':'synthetic-release','version':1,'content_sha256':'synthetic-release-hash'}},
        'author': {'entries': [], 'bindings': [], 'sources': []}, 'sources': {}})
    monkeypatch.setattr(app, '_profile_state', lambda owner: 'validated')
    artifact = app.artifacts.write(b'SYNTHETIC identity response', 'text/plain')
    async def identity(*args):
        return {'targets': [{'target_id': 'synthetic-target', 'main_id': 'SYNTHETIC OBJECT',
            'primary_otype': 'synthetic-type', 'classification_assertions': []}], 'artifact': artifact,
            'astrometric_evidence': []}
    monkeypatch.setattr(app.identity, 'resolve', identity)
    calls = []
    async def model(**kwargs):
        calls.append(kwargs['profile'].operation)
        if kwargs['profile'].operation == 'request_parser':
            return {'targets': [{'text': wording, 'start': 0, 'end': len(wording)}], 'properties': [],
                'conditions': [], 'unknown_fragments': [], 'property_operation': 'replace', 'clarification_needed': False}, {'attempt_id': 'synthetic-parser'}
        return answer(wording,pid='P1'), {'attempt_id': 'synthetic-semantic'}
    monkeypatch.setattr(app.models, 'json', model)
    tid = str(uuid4())
    app.create(wording, tid)
    async def run():
        first = app.repository.claim_job('synthetic-worker', task_id=tid)
        await app.prepare(first)
        assert app.view(tid)['draft']['status'] == 'processing'
        second = app.repository.claim_job('synthetic-worker', task_id=tid)
        assert second['payload']['selection_only']
        await app.prepare(second)
    asyncio.run(run())
    view = app.view(tid)
    assert calls == ['request_parser', 'property_selection', 'property_selection']
    draft, question = view['draft'], view['draft']['pending_question']
    assert draft['selected_property_ids'] == ['synthetic-cycle']
    assert [b['property_id'] for b in question['property_catalog']['bindings']] == ['synthetic-cycle']
    assert view['query_ref'] is None
    operation = {'protocol_version': 2, 'operation_id': str(uuid4()), 'expected_revision': view['revision'],
        'question_id': question['question_id'], 'action': {'type': 'select_properties', 'property_ids': ['synthetic-other']}}
    with pytest.raises(DomainError):
        app.draft_action(tid, operation)
    operation.update(operation_id=str(uuid4()), action={'type': 'confirm', 'preview_hash': question['preview']['preview_hash']})
    app.draft_action(tid, operation)
    assert calls == ['request_parser', 'property_selection', 'property_selection']  # Confirmation is local.
    with app.repository.read() as conn:
        spec = app.repository.objects(conn, tid, 'confirmed_query')[0]
        assert spec['property_selection']['resolution_ref']
        assert spec['knowledge_release']=={'id':'synthetic-author','version':1,'content_sha256':'a'*64}
        from astroquery_ai.runtime.run_policy import literature_strategy
        assert literature_strategy(spec)==expected_strategy
        assert spec['run_policy']['literature']['release']==release_version
        assert not spec['run_policy']['literature'].get('stop_after_materials')
        assert conn.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0


def test_changed_intent_invalidates_old_confirmation_before_model_completes(tmp_path):
    app = Application(tmp_path)
    tid = str(uuid4());app.create('SYNTHETIC original', tid)
    with app.repository.transaction() as conn:
        draft = app._draft(conn, tid)
        draft.update(fake_draft(), model_property_selection={'candidate_property_ids': ['synthetic-cycle'],
            'support_hash': 'synthetic-hash', 'target_id': 'synthetic-target', 'resolution_ref': {'id': 'synthetic-old'}})
        draft['selected_property_ids'] = ['synthetic-cycle']
        app._queue_property_selection(conn, draft, {'source_text': 'SYNTHETIC changed'}, 'synthetic-edit')
        draft = app._draft(conn, tid)
        app._save_draft(conn, draft)
    question = app.view(tid)['draft']['pending_question']
    assert question['preview'] is None
    assert not question['property_catalog']['bindings']


def test_none_and_ambiguous_candidates_keep_distinct_user_decisions():
    draft = fake_draft()
    a = answer('SYNTHETIC ambiguous')
    a['requests'][0]['candidates'].append({'property_id': 'synthetic-other', 'match': 'related', 'explanation': 'different definition'})
    a, _ = checked_selection(a, 'SYNTHETIC ambiguous', draft['property_support']['bindings'])
    resolve_property_requests(draft, {}, 'op', semantic=a)
    assert not draft['selected_property_ids'] and draft['issues'][0]['kind'] == 'ambiguous_property'
    b = answer('SYNTHETIC no equivalent', coverage='none')
    resolve_property_requests(draft, {}, 'op2', semantic=b)
    assert not draft['selected_property_ids']
    assert any(i.get('requires_omission') for i in draft['issues'])
    assert digest(draft['model_property_selection'])


def test_non_equivalent_related_suggestion_can_accompany_an_explicit_gap():
    draft = fake_draft()
    response = answer('SYNTHETIC unsupported', coverage='none')
    response['requests'][0]['candidates'] = [{'property_id': 'synthetic-other', 'match': 'related',
        'explanation': 'Different physical quantity, shown only as a related option'}]
    checked, _ = checked_selection(response, 'SYNTHETIC unsupported', draft['property_support']['bindings'])
    resolve_property_requests(draft, {}, 'op', semantic=checked)
    assert not draft['selected_property_ids']
    assert any(i.get('requires_omission') for i in draft['issues'])


def test_flat_model_ids_are_decoded_without_inventing_or_matching_property_names():
    response = answer('SYNTHETIC intent')
    request = response['requests'][0]
    request.pop('candidates')
    request.update(candidate_property_ids=['synthetic-cycle', 'synthetic-other'],
        equivalent_property_ids=['synthetic-cycle'], explanation='First is equivalent; second describes a related quantity')
    request.pop('end')  # No paid retry for a uniquely recoverable literal offset.
    checked, _ = checked_selection(response, 'SYNTHETIC intent', fake_draft()['property_support']['bindings'])
    assert [c['match'] for c in checked['requests'][0]['candidates']] == ['equivalent', 'related']
    request['candidate_property_ids'] = ['not-in-registry']
    with pytest.raises(DomainError):
        checked_selection(response, 'SYNTHETIC intent', fake_draft()['property_support']['bindings'])
