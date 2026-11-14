import asyncio
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
import inspect
import pytest

from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science import material_summaries, property_insight_generation


def bundle_module():
    from astroquery_ai.science import insight_bundle
    return insight_bundle


def test_children_support_report_only_generation():
    for fn in (material_summaries.generate, property_insight_generation.generate):
        assert 'publish' in inspect.signature(fn).parameters
        assert inspect.signature(fn).parameters['publish'].default is True
        assert 'knowledge_context' in inspect.signature(fn).parameters


def reports():
    delivery={'delivery_id':'d','snapshot_ref':{'id':'s','version':1},'revision':1}
    spec={'run_policy':{'insights':{'mode':'dot_author/1','presentation':'research-workbench/2'}},
          'knowledge_context_ref':{'id':'k','version':1,'content_sha256':'hash'}}
    material=material_summaries.report(delivery,state='generated',counts={'p':{'requested':1,'ready':1,'failed':0,'bibliography':0}})
    from astroquery_ai.science.property_insights import pending_report
    prop=pending_report(delivery,None);prop.update(status='complete',qualified_property_ids=['p'])
    for child in (material,prop):child['knowledge_context_ref']=deepcopy(spec['knowledge_context_ref'])
    return delivery,spec,material,prop


@pytest.mark.parametrize('branch', ['material','property'])
def test_partial_branch_preserves_other_and_context(branch):
    b=bundle_module();delivery,spec,material,prop=reports()
    failed=material if branch=='material' else prop
    failed.update(status='partial',reason='BUDGET_EXHAUSTED')
    result=b.compose(delivery,spec,material,prop)
    assert result['schema_version']=='InsightBundle/1'
    assert result['status']=='partial'
    assert result['knowledge_context_ref']==spec['knowledge_context_ref']
    assert result['material_report']==material and result['property_report']==prop
    assert result['components'][branch]['reason']=='BUDGET_EXHAUSTED'


def test_bundle_rejects_cross_snapshot_children():
    b=bundle_module();delivery,spec,material,prop=reports()
    prop['snapshot_ref']={'id':'other','version':1}
    with pytest.raises(DomainError) as exc:b.compose(delivery,spec,material,prop)
    assert exc.value.code=='INSIGHT_SNAPSHOT_CHANGED'


def test_pending_bundle_contains_two_pending_components():
    b=bundle_module();delivery,spec,_,_=reports()
    result=b.pending_report(delivery,spec)
    assert result['status']=='pending'
    assert {x['status'] for x in result['components'].values()}=={'pending'}


class Repo:
    def __init__(self):
        self.saved={};self.finished=0;self.task_body={'lifecycle':'running','delivery_ref':canonical({'id':'d','version':1}).decode()}
    @contextmanager
    def read(self):yield self
    transaction=read
    def task(self,c,tid):return self.task_body
    def validate_lease(self,c,job,scientific=False):
        if self.task_body['lifecycle']!='running':raise DomainError('DISPATCH_FORBIDDEN','paused')
    def objects(self,c,tid,kind):return deepcopy(list(self.saved.get(kind,{}).values()))
    def put_object(self,c,tid,kind,key,version,body):
        self.saved.setdefault(kind,{})[key]=deepcopy(body)
        return {'id':key,'version':version}
    def finish_job(self,c,job):self.finished+=1


@pytest.mark.parametrize('saved_branch', [None,'material','property'])
def test_barrier_reuses_completed_branch_and_finishes_once(monkeypatch,saved_branch):
    b=bundle_module();d,s,m,p=reports();repo=Repo();calls=[];published=[]
    class Delivery:
        def get(self,c,tid,did=None):return deepcopy(d)
        def finish_insights(self,c,tid,report):
            assert len(repo.saved['insight_bundle_component'])==2
            published.append(report)
    service=SimpleNamespace(repo=repo,app=SimpleNamespace(delivery=Delivery()))
    job={'task_id':'t','payload':{'delivery_id':'d'}}
    from astroquery_ai.science import task_knowledge
    monkeypatch.setattr(task_knowledge,'load',lambda *args:{'context_id':'k'})
    async def material(*args,**kwargs):
        assert kwargs['publish'] is False and kwargs['knowledge_context']=={'context_id':'k'}
        assert repo.finished==0 and not published
        calls.append('material');return m
    async def prop(*args,**kwargs):
        assert kwargs['publish'] is False and kwargs['knowledge_context']=={'context_id':'k'}
        assert repo.finished==0 and not published
        calls.append('property');return p
    monkeypatch.setattr(material_summaries,'generate',material)
    monkeypatch.setattr(property_insight_generation,'generate',prop)
    if saved_branch:
        b.save_component(repo,repo,'t',d,s,saved_branch,m if saved_branch=='material' else p)
    result=asyncio.run(b.generate(service,job,s))
    assert result['status']=='complete' and repo.finished==1 and len(published)==1
    assert calls==[x for x in ['material','property'] if x!=saved_branch]


def test_barrier_stale_revision_does_not_publish(monkeypatch):
    b=bundle_module();d,s,m,p=reports();repo=Repo()
    class Delivery:
        def get(self,c,tid,did=None):return deepcopy(d)
        def finish_insights(self,*args):pytest.fail('must not publish')
    service=SimpleNamespace(repo=repo,app=SimpleNamespace(delivery=Delivery()))
    from astroquery_ai.science import task_knowledge
    monkeypatch.setattr(task_knowledge,'load',lambda *args:{'context_id':'k'})
    async def material(*args,**kwargs):
        repo.task_body['delivery_ref']=canonical({'id':'d','version':2}).decode();return m
    monkeypatch.setattr(material_summaries,'generate',material)
    with pytest.raises(DomainError) as exc:asyncio.run(b.generate(service,{'task_id':'t','payload':{'delivery_id':'d'}},s))
    assert exc.value.code=='DELIVERY_CHANGED' and repo.finished==0

def test_bundle_export_metadata_adds_only_frozen_refs():
    from astroquery_ai.science.results.research_export import metadata
    d,s,m,p=reports();b=bundle_module().compose(d,s,m,p)
    body={**d,'measurements':[],'insight_report':b}
    meta=metadata(body)
    assert meta['knowledge_context_ref']==s['knowledge_context_ref']
    assert meta['insight_components']==b['components']
    legacy=metadata({**body,'insight_report':p})
    assert 'knowledge_context_ref' not in legacy and 'insight_components' not in legacy


def test_report_only_permit_cannot_authorize_property_science():
    from astroquery_ai.runtime.budget import Budget
    budget=object.__new__(Budget)
    with pytest.raises(DomainError) as exc:
        budget.reserve(task_id='t',owner='M11',model='qwen3.8-max',root_id='material-summary-call-test',
            request={},input_bound=10,output_bound=10,profile_state='report_only',purpose='production')
    assert exc.value.code=='PROFILE_NOT_VALIDATED'


def test_new_confirmations_choose_bundle_without_mutating_old_templates():
    from astroquery_ai.runtime.run_policy import request_policy, RESEARCH_DELIVERY_POLICY
    before=deepcopy(RESEARCH_DELIVERY_POLICY)
    config=SimpleNamespace(runtime={})
    assert request_policy(config)['insights']['presentation']=='research-workbench/2'
    assert RESEARCH_DELIVERY_POLICY==before and before['insights']['presentation']=='research-property/1'

def test_interrupted_material_counts_include_unstarted_sources(tmp_path, monkeypatch):
    from tests.rebuild.scenario import application
    from tests.rebuild.test_research_exports import fixture
    from astroquery_ai.science import task_knowledge
    b=bundle_module();app=application(tmp_path/'data');repo=app.repository
    tid=repo.create_task('synthetic interrupted bundle')['task_id']
    d=fixture();d['sources'].append({'source_id':'second','kind':'catalog','readme':{'text':'Saved full material'}})
    d['coverage']=[{'source_id':'second','property_id':'p-temperature'}]
    _,s,_,_=reports()
    prop=__import__('astroquery_ai.science.property_insights',fromlist=['pending_report']).pending_report(d,None)
    prop.update(status='partial')
    monkeypatch.setattr(task_knowledge,'load',lambda *args:None)
    monkeypatch.setattr(property_insight_generation,'unfinished_report',lambda *args,**kwargs:deepcopy(prop))
    with repo.transaction() as c:
        row={'snapshot_ref':d['snapshot_ref'],'material_id':'s1','property_id':'p-temperature','state':'ready'}
        repo.put_object(c,tid,'material_summary',material_summaries._identity(d,'s1','p-temperature'),1,row)
        result=b.unfinished_report(repo,c,tid,d,s,'user_cancelled')
    count=result['material_report']['counts']['p-temperature']
    assert count['ready']==1 and count['requested']==2

def test_final_bundle_revision_matches_containing_publication():
    b=bundle_module();d,s,m,p=reports()
    report=b.compose(d,s,m,p)
    assert report['delivery_revision']==d['revision']+1
    assert report['generation_delivery_revision']==d['revision']
    assert b.pending_report(d,s)['delivery_revision']==d['revision']

def test_property_component_call_count_excludes_material_permits(tmp_path, monkeypatch):
    from tests.rebuild.scenario import application
    from astroquery_ai.science import task_knowledge
    app=application(tmp_path/'data');repo=app.repository
    tid=repo.create_task('synthetic call accounting')['task_id']
    d,s,_,_=reports();d['measurements']=[];s['properties']=[]
    monkeypatch.setattr(task_knowledge,'load',lambda *args:None)
    with repo.transaction() as c:
        campaign=c.execute('SELECT campaign_id FROM campaigns LIMIT 1').fetchone()[0]
        for aid,root in [('property','author-unit-test:primary'),('material','material-summary-call-test')]:
            c.execute('INSERT INTO attempts(attempt_id,campaign_id,task_id,root_id,owner,model,request_hash,price_version,status,reserved_micros,actual_micros,input_bound,output_bound,smoke,created_at,generation) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (aid,campaign,tid,root,'M11','qwen3.8-max','hash','fixture','settled',0,0,1,1,0,'fixture',1))
        report=property_insight_generation.unfinished_report(repo,c,tid,d,s,'fixture')
    assert report['model_calls']==1

@pytest.mark.parametrize('part', ['id','version','content_sha256'])
@pytest.mark.parametrize('branch', ['material','property'])
def test_compose_rejects_child_knowledge_reference_mismatch(part,branch):
    b=bundle_module();d,s,m,p=reports()
    for child in (m,p):child['knowledge_context_ref']=deepcopy(s['knowledge_context_ref'])
    child=m if branch=='material' else p
    child['knowledge_context_ref'][part]=2 if part=='version' else 'wrong'
    with pytest.raises(DomainError) as exc:b.compose(d,s,m,p)
    assert exc.value.code=='TASK_KNOWLEDGE_HASH'


@pytest.mark.parametrize('part', ['id','version','content_sha256'])
@pytest.mark.parametrize('location', ['envelope','report'])
def test_resume_rejects_component_context_before_any_dispatch(monkeypatch,part,location):
    b=bundle_module();d,s,m,p=reports();repo=Repo()
    for child in (m,p):child['knowledge_context_ref']=deepcopy(s['knowledge_context_ref'])
    saved=b.save_component(repo,repo,'t',d,s,'property',p)
    stored=repo.saved['insight_bundle_component'][saved['component_id']]
    target=stored if location=='envelope' else stored['report']
    target['knowledge_context_ref'][part]=2 if part=='version' else 'wrong'
    class Delivery:
        def get(self,*args):return deepcopy(d)
        def finish_insights(self,*args):pytest.fail('mismatched context must not publish')
    service=SimpleNamespace(repo=repo,app=SimpleNamespace(delivery=Delivery()))
    from astroquery_ai.science import task_knowledge
    monkeypatch.setattr(task_knowledge,'load',lambda *args:{'context_id':'k'})
    async def forbidden(*args,**kwargs):pytest.fail('validate all recovered scopes before dispatch')
    monkeypatch.setattr(material_summaries,'generate',forbidden)
    monkeypatch.setattr(property_insight_generation,'generate',forbidden)
    with pytest.raises(DomainError) as exc:asyncio.run(b.generate(service,{'task_id':'t','payload':{'delivery_id':'d'}},s))
    assert exc.value.code=='TASK_KNOWLEDGE_HASH'
    assert repo.finished==0


def test_pending_and_reconstructed_failed_children_carry_pinned_context(tmp_path,monkeypatch):
    from tests.rebuild.scenario import application
    from tests.rebuild.test_research_exports import fixture
    from astroquery_ai.science import task_knowledge
    b=bundle_module();_,s,_,_=reports();d=fixture();s['properties']=[]
    pending=b.pending_report(d,s)
    for key in ('material_report','property_report'):
        assert pending[key]['knowledge_context_ref']==s['knowledge_context_ref']
    app=application(tmp_path/'data');tid=app.repository.create_task('failed child scope')['task_id']
    monkeypatch.setattr(task_knowledge,'load',lambda *args:None)
    with app.repository.read() as c:failed=b.unfinished_report(app.repository,c,tid,d,s,'TASK_KNOWLEDGE_MISSING')
    assert failed['status']=='partial'
    for key in ('material_report','property_report'):
        assert failed[key]['knowledge_context_ref']==s['knowledge_context_ref']


def test_conditional_material_wire_preserves_scope_and_provenance_without_changing_legacy():
    from tests.rebuild.test_research_exports import fixture
    from astroquery_ai.application.material_workbench import MaterialIndex
    d=fixture();index=MaterialIndex(d);group=index.groups['s1'];pid='p-temperature'
    block={'title':'Method','claim':{'claim_id':'c','text':'Use this method.'},
        'entry_id':'entry','conditions':['ONLY under LTE'], 'applicability_state':'conditional',
        'origin':'formal_release','authoring_basis':'author_knowledge','sources':[{'source_id':'original'}],
        'knowledge_release_ref':{'id':'release','version':1,'content_sha256':'r'},'content_sha256':'block-hash'}
    _,spec,_,_=reports();ref=spec['knowledge_context_ref']
    payload,basis=material_summaries.SummaryInputs(d,index,{pid:[block]},knowledge_context_ref=ref).pack(group,[pid])
    actual=payload['properties'][0]['knowledge_background'][0]
    assert actual['conditions']==['ONLY under LTE']
    assert actual['applicability_state']=='conditional'
    for key in ('entry_id','origin','authoring_basis','sources','knowledge_release_ref','content_sha256'):
        assert actual[key]==block[key]
    assert actual['claim_id']=='c'
    assert payload['knowledge_context_ref']==ref
    assert payload['knowledge_policy']['role']=='background_not_source_facts'
    assert basis['P1']['knowledge']==[block]
    legacy,_=material_summaries.SummaryInputs(d,index,{pid:[block]}).pack(group,[pid])
    assert legacy['properties'][0]['knowledge_background']==[{'title':'Method','text':'Use this method.'}]
    assert 'knowledge_policy' not in legacy and 'knowledge_context_ref' not in legacy


@pytest.mark.parametrize('bundle', [True,False])
def test_pending_material_detail_recognizes_bundle_and_legacy(monkeypatch,bundle):
    from tests.rebuild.test_research_exports import fixture
    from astroquery_ai.application.material_workbench import MaterialIndex
    d=fixture();index=MaterialIndex(d)
    report=material_summaries.report(d,state='pending')
    d['insight_report']={'schema_version':'InsightBundle/1','material_report':report} if bundle else report
    monkeypatch.setattr(material_summaries,'stored_summary',lambda *args,**kwargs:None)
    assert material_summaries.read_summary(None,None,'t',d,index.groups['s1'],'p-temperature')['state']=='pending'

def test_frozen_material_claim_keeps_restriction_after_legacy_text_cutoff():
    from tests.rebuild.test_research_exports import fixture
    from astroquery_ai.application.material_workbench import MaterialIndex
    d=fixture();index=MaterialIndex(d);pid='p-temperature'
    claim='Background explanation. '*30+'Only apply when the original material proves LTE.'
    block={'title':'Method','claim':{'claim_id':'c','text':claim},'conditions':[],
           'applicability_state':'unknown','origin':'user_background'}
    _,spec,_,_=reports()
    payload,_=material_summaries.SummaryInputs(d,index,{pid:[block]},
        knowledge_context_ref=spec['knowledge_context_ref']).pack(index.groups['s1'],[pid])
    assert payload['properties'][0]['knowledge_background'][0]['text']==claim
