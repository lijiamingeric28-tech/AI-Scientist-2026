"""Sealed knowledge must never follow edits to the live library."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from astroquery_ai.runtime.codec import digest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.science.user_knowledge_store import UserKnowledgeStore


def case(tmp_path):
    store=UserKnowledgeStore(resource_dir=tmp_path/'empty',data_dir=tmp_path/'library')
    user=store.create_user_entry({'title':'Frozen temperature','description':'original private background',
        'properties':['effective_temperature'],'entity_types':['Star'],'conditions':['LTE unknown'],'sources':'private source'})
    unrelated=store.create_user_entry({'title':'unrelated','description':'radius only','properties':['radius']})
    wrong=store.create_user_entry({'title':'wrong scope','description':'galaxy only',
        'properties':['effective_temperature'],'entity_types':['Galaxy']})
    b={'property_id':'effective_temperature','definition':{'property_id':'effective_temperature','definition_version':'1','content_sha256':'def','name_cn':'有效温度'},
        'output_profile':{'profile_id':'temperature','version':'1','content_sha256':'prof'},
        'rule_refs':[{'id':'star-rule','version':'1','content_sha256':'rule'}]}
    ref={'id':'release','version':1,'content_sha256':'release-hash'}
    spec={'run_policy':{'insights':{'mode':'dot_author/1','presentation':'research-workbench/2'}},'knowledge_release':ref,'properties':[b],
        'target':{'target_id':'star','primary_otype':'Star'}}
    release={'manifest':{'release_id':'release','content_sha256':'release-hash'},'sources':{'s':{'source_id':'s','title':'original source'}},
        'author':{'entries':[{'entry_id':'formal','title':'Formal','conditions':[],'blocks':[{'text':'original formal',
        'role':'meaning','basis':'source_checked','source_ids':['s']}]}], 'sources':[],
        'bindings':[{'item_id':'binding','otype':'Star','property_id':'effective_temperature',
        'definition_ref':{'id':'effective_temperature','version':'1','content_sha256':'def'},
        'output_profile_ref':{'id':'temperature','version':'1','content_sha256':'prof'},'applicability_rule_refs':b['rule_refs'],
        'entry_ids':['formal'],'status':'covered','reason':''}]}}
    repo=Repository(tmp_path/'db.sqlite');tid=repo.create_task('synthetic')['task_id']
    app=SimpleNamespace(user_knowledge=store,knowledge=SimpleNamespace(load=lambda reference:deepcopy(release)),repository=repo)
    return app,spec,tid,release,user['id'],unrelated['id'],wrong['id']


def test_pin_freezes_exact_content_and_scoped_background(tmp_path):
    from astroquery_ai.science import task_knowledge as tk
    app,spec,tid,release,uid,unrelated,wrong=case(tmp_path)
    with app.repository.transaction() as conn:ref=tk.pin(app,conn,tid,spec)
    assert spec['knowledge_context_ref']==ref
    release['author']['entries'][0]['blocks'][0]['text']='changed formal'
    app.user_knowledge.update_entry(uid,{'description':'changed private','expected_revision':app.user_knowledge.get_entry(uid)['revision']})
    with app.repository.read() as conn:context=tk.load(app.repository,conn,tid,spec)
    entries=context['entries'];ids={e['entry_id'] for e in entries}
    assert ids=={'formal',uid} and unrelated not in ids and wrong not in ids
    claims=tk.blocks(context,'effective_temperature')
    assert {b['claim']['text'] for b in claims}=={'original formal','original private background'}
    assert claims[0]['claim']['claim_id']=='kb-block-'+digest(['release-hash','formal',0])
    frozen=tk.frozen_user_store(context)
    assert frozen.get_entry(uid)['description']=='original private background'
    assert frozen.search(field_names=['radius'],keywords=['temperature'],top_k=20)==[]
    assert {e['entry_id'] for e in tk.blocks(context)}==ids
    claims[0]['claim']['text']='tampered copy'
    assert tk.blocks(context)[0]['claim']['text']=='original formal'
    assert next(e for e in entries if e['entry_id']==uid)['applicability_state']=='conditional'


def test_historical_without_ref_is_read_only_and_hash_corruption_rejected(tmp_path):
    from astroquery_ai.science import task_knowledge as tk
    app,spec,tid,*_=case(tmp_path)
    with app.repository.read() as conn:
        before=conn.total_changes
        assert tk.load(app.repository,conn,tid,{'run_policy':{}}) is None
        assert conn.total_changes==before
    context=tk.capture(app,spec);context['entries'][0]['claim']['text']='corrupt'
    with pytest.raises(DomainError) as exc:tk.blocks(context)
    assert exc.value.code=='TASK_KNOWLEDGE_HASH'


def test_no_match_and_unreadable_have_distinct_property_states(tmp_path):
    from astroquery_ai.science import task_knowledge as tk
    app,spec,tid,release,*_=case(tmp_path)
    spec['properties'][0]['property_id']='unmapped';spec['properties'][0]['definition']['property_id']='unmapped'
    assert tk.capture(app,spec)['properties'][0]['state']=='missing'
    def unavailable(reference):raise DomainError('KB_MISSING','missing')
    app.knowledge.load=unavailable
    assert tk.capture(app,spec)['properties'][0]['state']=='unavailable'

def test_copilot_bundle_reads_bundle_property_cards_and_sealed_knowledge(tmp_path):
    from astroquery_ai.science import task_knowledge as tk
    from astroquery_ai.agent_harness.data_loader import TaskDataBundle
    from astroquery_ai.agent_harness.tools import DomainTools
    from astroquery_ai.agent_harness.controller import AgentController
    app,spec,tid,release,uid,*_=case(tmp_path)
    context=tk.capture(app,spec)
    report={'schema_version':'InsightBundle/1','knowledge_context_ref':{'id':context['context_id']},
        'property_report':{'cards':[{'card_id':'sealed-card'}],'knowledge_blocks':[]},
        'material_report':{'schema_version':'MaterialSummaryReport/1'}}
    body={'delivery_id':'delivery','snapshot_ref':{'id':'snapshot'},'definitions':spec['properties'],
        'insight_report':report,'knowledge_context':context}
    bundle=TaskDataBundle(tid,body)
    app.user_knowledge.delete_entry(uid,expected_revision=app.user_knowledge.get_entry(uid)['revision'])
    release['author']['entries'][0]['blocks'][0]['text']='changed live formal'
    tools=DomainTools(bundle,knowledge_store=app.user_knowledge)
    answer=tools.execute_tool('get_scientific_theory',{'property_name':'effective_temperature'})
    assert 'original private background' in answer and 'original formal' in answer
    assert 'changed live' not in answer
    assert bundle.insight_cards==[{'card_id':'sealed-card'}]
    assert AgentController(bundle,application=app).tools.knowledge_store.get_entry(uid)['description']=='original private background'
    assert tools.execute_tool('get_scientific_theory',{'property_name':'radius'}).find('original formal')==-1


def test_exact_formal_versions_rules_and_types_are_never_relaxed(tmp_path):
    from astroquery_ai.science import task_knowledge as tk
    app,spec,tid,release,*_=case(tmp_path)
    app.user_knowledge=UserKnowledgeStore(resource_dir=tmp_path/'empty',data_dir=tmp_path/'unused')
    original=deepcopy(release['author']['bindings'][0])
    for mutate in (
        lambda b:b['definition_ref'].update(version='2'),
        lambda b:b['output_profile_ref'].update(content_sha256='other'),
        lambda b:b.update(applicability_rule_refs=[]),
        lambda b:b.update(otype='Galaxy'),
    ):
        binding=deepcopy(original);mutate(binding);release['author']['bindings']=[binding]
        context=tk.capture(app,spec)
        assert tk.blocks(context)==[] and context['properties'][0]['state']=='missing'


def test_frozen_store_does_not_invent_cross_property_relationships(tmp_path):
    from astroquery_ai.science import task_knowledge as tk
    app,spec,*_=case(tmp_path)
    context=tk.capture(app,spec)
    assert tk.frozen_theory_store(context).derive_network_relationships(['mass','radius'])==[]
    assert tk.frozen_user_store(context).get_preferred_ids()==set()

def test_loader_reads_pinned_context_instead_of_current_library(tmp_path):
    from astroquery_ai.science import task_knowledge as tk
    from astroquery_ai.runtime.codec import canonical,digest
    from astroquery_ai.agent_harness.data_loader import load_task_bundle
    from astroquery_ai.agent_harness.tools import DomainTools
    app,spec,tid,release,uid,*_=case(tmp_path)
    with app.repository.transaction() as conn:
        tk.pin(app,conn,tid,spec)
        spec['spec_hash']=digest(spec)
        ref=app.repository.put_object(conn,tid,'confirmed_query','query',1,spec)
        app.repository.mutate_task(conn,tid,query_ref=canonical(ref).decode())
    body={'delivery_id':'delivery','revision':2,'snapshot_ref':{'id':'snapshot'},'definitions':spec['properties']}
    app.delivery=SimpleNamespace(read_for_display=lambda *args:deepcopy(body),
        display_scope=lambda *args:{'source':tid,'summary_before':None})
    app.history=SimpleNamespace(source=lambda *args:tid)
    app.user_knowledge.delete_entry(uid,expected_revision=app.user_knowledge.get_entry(uid)['revision'])
    release['author']['entries'][0]['blocks'][0]['text']='new release text'
    loaded=load_task_bundle(tid,app)
    output=DomainTools(loaded,knowledge_store=app.user_knowledge).execute_tool('get_scientific_theory',{'property_name':'effective_temperature'})
    assert 'original private background' in output and 'original formal' in output
    assert 'new release text' not in output

@pytest.mark.parametrize('code',['KB_MANIFEST_HASH','KB_RELEASE_SCHEMA','KB_REVOKED','KB_UNAVAILABLE'])
def test_invalid_formal_release_is_rejected_instead_of_unavailable(tmp_path,code):
    from astroquery_ai.science import task_knowledge as tk
    app,spec,*_=case(tmp_path)
    def invalid(reference):raise DomainError(code,'synthetic rejection')
    app.knowledge.load=invalid
    with pytest.raises(DomainError) as exc:tk.capture(app,spec)
    assert exc.value.code==code


@pytest.mark.parametrize('code',['KB_MISSING','KB_MANIFEST_HASH'])
def test_confirmation_pins_unreadable_known_release_before_spec_hash(tmp_path,monkeypatch,code):
    import asyncio
    from uuid import uuid4
    from astroquery_ai.runtime.scheduler import Scheduler
    from astroquery_ai.runtime.codec import digest
    from tests.rebuild.scenario import application,synthetic_author_manifest,run_until_wait
    async def run():
        app=application(tmp_path/'confirm');manifest=synthetic_author_manifest(app)
        task=app.create('SYNTHETIC_AQ 测试长度',str(uuid4()));scheduler=Scheduler(app)
        await run_until_wait(app,scheduler);state=app.view(task['task_id'])
        def fail(reference=None):raise DomainError(code,'synthetic unreadable')
        app.knowledge.load=fail
        monkeypatch.setattr('astroquery_ai.runtime.run_policy.request_policy',lambda *args:{'insights':{
            'mode':'dot_author/1','presentation':'research-workbench/2'}})
        request={'protocol_version':2,'operation_id':str(uuid4()),'expected_revision':state['revision'],
            'question_id':state['pending']['question_id'],'action':{'type':'confirm',
            'preview_hash':state['pending']['preview']['preview_hash']}}
        if code!='KB_MISSING':
            with pytest.raises(DomainError) as exc:app.draft_action(task['task_id'],request)
            assert exc.value.code==code
            return
        app.draft_action(task['task_id'],request)
        with app.repository.read() as conn:
            spec=app.repository.objects(conn,task['task_id'],'confirmed_query')[0]
            assert spec['knowledge_release']['id']=='synthetic-author'
            assert spec['spec_hash']==digest({k:v for k,v in spec.items() if k!='spec_hash'})
            from astroquery_ai.science.task_knowledge import load
            context=load(app.repository,conn,task['task_id'],spec)
            assert context['properties'][0]['formal_state']=='unavailable'
    asyncio.run(run())

def test_historical_pin_never_writes_and_reference_tamper_rejects(tmp_path):
    from astroquery_ai.science import task_knowledge as tk
    app,spec,tid,*_=case(tmp_path)
    with app.repository.transaction() as conn:
        old={'run_policy':{'insights':{'mode':'dot_author/1','presentation':'research-property/1'}}}
        before=conn.total_changes
        assert tk.pin(app,conn,tid,old) is None
        assert conn.total_changes==before and 'knowledge_context_ref' not in old
        tk.pin(app,conn,tid,spec)
    tampered=deepcopy(spec);tampered['knowledge_context_ref']['content_sha256']='bad'
    with app.repository.read() as conn:
        with pytest.raises(DomainError) as exc:tk.load(app.repository,conn,tid,tampered)
    assert exc.value.code=='TASK_KNOWLEDGE_HASH'

def test_rejected_formal_author_cannot_reenter_through_builtin_store(tmp_path):
    from astroquery_ai.science import task_knowledge as tk
    app,spec,tid,release,*_=case(tmp_path)
    release['author']['bindings'][0]['definition_ref']['version']='obsolete'
    store=UserKnowledgeStore(resource_dir=tmp_path/'empty',data_dir=tmp_path/'author-overlay')
    raw={'id':'formal','title':'obsolete formal','description':'obsolete unbound formal text',
        'properties':['effective_temperature'],'entity_types':['Star'],'origin':'author_entry',
        'is_user':False,'is_override':False,'conditions':[]}
    store.base_entries=[raw];store.base_entries_by_id={'formal':raw};app.user_knowledge=store
    context=tk.capture(app,spec)
    assert tk.blocks(context)==[]
    assert context['properties'][0]['state']=='missing'
    store.update_entry('formal',{'description':'explicit user background','conditions':['user applicability unknown']})
    context=tk.capture(app,spec)
    assert len(tk.blocks(context))==1
    selected=tk.blocks(context)[0]
    assert selected['origin']=='user_background' and selected['applicability_state']=='conditional'
    assert selected['claim']['text']=='explicit user background'
    assert not selected.get('applicable_mappings') and not selected.get('knowledge_release_ref')


def test_scoped_copilot_rejects_unrelated_property_title_collision(tmp_path):
    from astroquery_ai.science import task_knowledge as tk
    from astroquery_ai.agent_harness.data_loader import TaskDataBundle
    from astroquery_ai.agent_harness.tools import DomainTools
    app,spec,tid,release,uid,*_=case(tmp_path)
    app.user_knowledge.update_entry(uid,{'title':'radius discussion for temperature'})
    body={'definitions':spec['properties'],'knowledge_context':tk.capture(app,spec)}
    bundle=TaskDataBundle(tid,body)
    answer=DomainTools(bundle).execute_tool('get_scientific_theory',{'property_name':'radius'})
    assert 'original private background' not in answer and '[THEORY:' not in answer

@pytest.mark.parametrize('same_property',[False,True])
def test_historical_saved_claim_versions_survive_helper_loader_and_copilot(tmp_path,same_property):
    from astroquery_ai.science import task_knowledge as tk
    from astroquery_ai.science.material_summaries import _identity
    from astroquery_ai.runtime.codec import canonical,digest
    from astroquery_ai.agent_harness.data_loader import load_task_bundle
    from astroquery_ai.agent_harness.tools import DomainTools
    from astroquery_ai.agent_harness.verifier import GroundingVerifier
    app,spec,tid,release,*_=case(tmp_path)
    radius=deepcopy(spec['properties'][0]);radius.update(property_id='radius')
    radius['definition'].update(property_id='radius',name_cn='半径')
    spec['properties'].append(radius)
    spec['run_policy']['insights']['presentation']='material-summary/1'
    body={'delivery_id':'delivery','revision':2,'snapshot_ref':{'id':'snapshot'},'definitions':spec['properties'],
          'insight_report':{'schema_version':'MaterialSummaryReport/1'}}
    with app.repository.transaction() as conn:
        spec['spec_hash']=digest(spec)
        ref=app.repository.put_object(conn,tid,'confirmed_query','query',1,spec)
        app.repository.mutate_task(conn,tid,query_ref=canonical(ref).decode())
        for pid,mid,text in [('effective_temperature','material-a','first archived temperature version'),
                             ('radius','material-b','second archived radius version')]:
            if same_property:pid='effective_temperature'
            block={'claim':{'claim_id':'shared-claim','text':text,'role':'meaning'},'entry_id':'shared-entry',
                   'title':'Saved background','sources':[],'conditions':[]}
            saved={'snapshot_ref':body['snapshot_ref'],'property_id':pid,'material_id':mid,
                   'basis':{'property_id':pid,'knowledge':[block]}}
            app.repository.put_object(conn,tid,'material_summary',_identity(body,mid,pid),1,saved)
    app.delivery=SimpleNamespace(read_for_display=lambda *args:deepcopy(body),
        display_scope=lambda *args:{'source':tid,'summary_before':None})
    app.history=SimpleNamespace(source=lambda *args:tid)
    bundle=load_task_bundle(tid,app)
    assert len(bundle.knowledge_context['entries'])==2
    store=tk.frozen_user_store(bundle.knowledge_context)
    for saved in bundle.theories:
        assert store.resolve_cached_block(saved)['claim']['text']==saved['claim']['text']
    tools=DomainTools(bundle,knowledge_store=app.user_knowledge)
    first_answer=tools.execute_tool('get_scientific_theory',{'property_name':'effective_temperature'})
    answers=[first_answer]
    if not same_property:
        assert [b['claim']['text'] for b in bundle.theories_by_prop['effective_temperature']]==['first archived temperature version']
        assert [b['claim']['text'] for b in bundle.theories_by_prop['radius']]==['second archived radius version']
        second_answer=tools.execute_tool('get_scientific_theory',{'property_name':'radius'})
        assert 'second archived radius version' not in first_answer
        assert 'first archived temperature version' not in second_answer
        answers.append(second_answer)
    else:
        assert len(bundle.theories_by_prop['effective_temperature'])==2
    # Ground only after ALL retrievals, as in a normal multi-tool answer.
    import re
    cited={}
    for answer in answers:
        parts=re.split(r'\[THEORY:([^\]]+)\]',answer)
        for marker,segment in zip(parts[1::2],parts[2::2]):
            expected=next(text for text in ('first archived temperature version','second archived radius version') if text in segment)
            assert marker not in cited or cited[marker]==expected
            cited[marker]=expected
    assert len(cited)==2
    verifier=GroundingVerifier(bundle)
    for marker,expected in cited.items():
        assert verifier.resolve('THEORY:'+marker)['payload']['block']['claim']['text']==expected
    clean,citations=verifier.verify_and_clean(' '.join('[THEORY:'+marker+']' for marker in cited))
    assert len(citations)==2 and len({c['citation_id'] for c in citations})==2
    assert {c['payload']['block']['claim']['text'] for c in citations}==set(cited.values())
    for marker,expected in cited.items():
        repeated=tools.execute_tool('get_scientific_theory',{'property_name':'','theory_id':marker})
        assert expected in repeated and '[THEORY:'+marker+']' in repeated
    ambiguous=tools.execute_tool('get_scientific_theory',{'property_name':'','theory_id':'shared-claim'})
    assert '[THEORY:' not in ambiguous
    assert verifier.resolve('THEORY:shared-claim') is None
    assert {b['claim']['claim_id'] for b in bundle.theories}=={'shared-claim'}
