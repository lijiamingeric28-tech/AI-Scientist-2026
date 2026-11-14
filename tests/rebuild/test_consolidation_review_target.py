"""Synthetic post-comparison answer application; not a scientific source judgment."""
import asyncio
from copy import deepcopy
from uuid import uuid4
import pytest
from astroquery_ai.runtime.codec import canonical,digest,content_hash
from astroquery_ai.runtime.run_policy import CONSOLIDATION_RUN_POLICY
from astroquery_ai.runtime.reviews import ReviewAnswer
from astroquery_ai.science.workflow.context import ScienceContext
from astroquery_ai.science.workflow.quality_service import QualityService
from tests.rebuild.scenario import application,confirmed_case


def test_review_ui_simulation_identity_requires_explicit_authorized_operator_mode(tmp_path):
 app=application(tmp_path)
 tid=app.create('SYNTHETIC_AQ 测试长度',str(uuid4()))['task_id']
 assert app.view(tid)['review_actor']=={'simulation':False,'kind':'local_user'}
 scope={'schema_version':'NormalQueryAcceptance/1','task_id':tid,'simulation_authorized':True}
 with app.repository.transaction() as c:app.repository.put_object(c,tid,'query_acceptance_run',tid,1,scope)
 assert app.view(tid)['review_actor']['simulation'] is False
 scope['operator_mode']='simulation'
 with app.repository.transaction() as c:app.repository.put_object(c,tid,'query_acceptance_run',tid,2,scope)
 assert app.view(tid)['review_actor']=={'simulation':True,'kind':'simulated_test_operator'}

@pytest.mark.parametrize('action',['correct','unable','confirm'])
def test_comparison_answer_changes_only_selected_record_and_unable_preserves_all(tmp_path,action):
 async def run():
  app=application(tmp_path);old,_=await confirmed_case(app)
  tid=app.repository.create_task('SYNTHETIC post-comparison answer scope')['task_id']
  with app.repository.transaction() as c:
   spec=deepcopy(app.repository.objects(c,old['task_id'],'confirmed_query')[0]);spec.update(task_id=tid,spec_id=tid,run_policy=deepcopy(CONSOLIDATION_RUN_POLICY))
   draft=deepcopy(app._draft(c,old['task_id']));draft['task_id']=tid
   app.repository.put_object(c,tid,'draft',tid,1,draft)
   spec['spec_hash']=digest({k:v for k,v in spec.items() if k!='spec_hash'})
   for row in c.execute("select kind,object_id,version,payload from objects where task_id=? and kind in ('source','qualification','object_match','evidence','context','interpretation','source_unit','unit','uncertainty_record','admission','error_basis','measurement')",(old['task_id'],)).fetchall():
    from astroquery_ai.runtime.codec import loads
    app.repository.put_object(c,tid,row['kind'],row['object_id'],row['version'],loads(row['payload']))
   q=app.repository.put_object(c,tid,'confirmed_query',tid,1,spec)
   app.repository.mutate_task(c,tid,lifecycle='running',science_state='open',query_ref=canonical(q).decode())
   app.repository.put_object(c,tid,'query_acceptance_run',tid,1,{'schema_version':'NormalQueryAcceptance/1','task_id':tid,'simulation_authorized':True,'synthetic':True})
   r=app.repository.objects(c,tid,'measurement')[0];other=deepcopy(r);other['measurement_id']='synthetic-other';other['content_sha256']=content_hash(other)
   app.repository.put_object(c,tid,'measurement',other['measurement_id'],1,other)
   records=[r,other];refs={x['measurement_id']:{'id':x['measurement_id'],'version':1,'content_sha256':x['content_sha256']} for x in records}
   evidence=app.repository.object(c,tid,'evidence',r['evidence_refs'][0]['id'])
   artifact,_=app.artifacts.read_owned(old['task_id'],evidence['artifact_ref']['id']);app.artifacts.register(c,tid,'synthetic-test-original',artifact)
   question=app.reviews.register(c,tid,{'origin':'M09','owner':'M03','issue_kind':'comparison_contradiction','issue_key':'synthetic-group','group_key':'synthetic-group',
    'question':'SYNTHETIC exercise target selection, not an actual scientific contradiction','impact':'test only',
    'scope':{'measurement_ids':list(refs)},'basis':{'spec_hash':spec['spec_hash'],'measurement_refs':refs},'evidence_refs':r['evidence_refs'],
    'record_interpretations':{x['measurement_id']:{'evidence_refs':x['evidence_refs']} for x in records},
    'allowed_actions':['confirm','correct','unable'],'correction_types':['correct_unit'],'approved_conditions':[]})
  correction={'type':'correct_unit','unit':'m','representation':'linear','representation_parameters':{'kind':'linear'},'evidence_ref':r['evidence_refs'][0],'quote':evidence['raw_text']} if action=='correct' else None
  outcome='different_conditions' if action=='confirm' else 'unresolved' if action=='unable' else None
  answer=ReviewAnswer(task_id=tid,review_id=question['review_id'],review_revision=question['revision'],basis_hash=question['basis_hash'],client_request_id=str(uuid4()),action=action,simulation=True,reason='' if action=='unable' else 'SYNTHETIC exact saved unit; target-scope check only',correction=correction,correction_measurement_id=r['measurement_id'] if action=='correct' else None,comparison_outcome=outcome)
  result=app.reviews.answer(answer);assert app.reviews.answer(answer)==result
  job=app.repository.claim_job('test-apply',task_id=tid,lease_seconds=600);assert job['kind']=='apply_review'
  await QualityService(ScienceContext(app)).apply_review(job)
  with app.repository.read() as c:
   first=app.repository.object(c,tid,'measurement',r['measurement_id']);second=app.repository.object(c,tid,'measurement',other['measurement_id'])
   assert second==other
   assert first['revision']==(2 if action=='correct' else 1)
   review=app.reviews.list(c,tid)[0];assert review['application']['status']=='applied'
   assert review['status']==('unable' if action=='unable' else 'resolved')
   if action != 'correct':
    assert first==r
    assert review['answer']['comparison_outcome']==outcome
    assert review['application']['comparison_outcome']==outcome
    assert all(item['comparison_outcome']==outcome for item in review['application']['results'])
    assert review['application']['postcheck']==('unresolved' if action=='unable' else 'passed')
    if action=='unable':assert review['answer']['reason']==''
   if action=='correct':assert first['unit']=='m' and first['value']==r['value']
  # Captured answers are presentation-only history, never pending questions.
  task=app.repository.get_task(tid)
  app.repository.control(tid,'cancel',str(uuid4()),task['revision'])
  replay=app.history.replay(tid,100,str(uuid4()))
  view=app.view(replay['task_id'])
  assert view['reviews']==[] and view['pending'] is None
  saved=view['replay']['saved_reviews'][0]
  assert saved['answer']['action']==action and saved['answer']['simulation'] is True
  assert saved['application']==review['application']
  with app.repository.read() as c:
   assert c.execute('select count(*) from jobs where task_id=?',(replay['task_id'],)).fetchone()[0]==0
   assert c.execute('select count(*) from attempts where task_id=?',(replay['task_id'],)).fetchone()[0]==0
 asyncio.run(run())
