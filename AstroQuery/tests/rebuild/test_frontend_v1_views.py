"""Read-only presentation contracts; synthetic fixtures, zero model calls."""
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from astroquery_ai.api.http import create_app
from astroquery_ai.application.presentation import presentation, redacted
from astroquery_ai.runtime.codec import canonical

def test_new_ui_endpoints_are_read_only_and_have_nine_stages(tmp_path):
    api=create_app(tmp_path,start_worker=False)
    with TestClient(api) as client:
        task=client.post('/api/tasks',json={'query':'SYNTHETIC request','operation_id':str(uuid4())}).json()
        tid=task['task_id'];app=api.state.application
        before=client.get(f'/api/tasks/{tid}/state').json()
        p=client.get(f'/api/tasks/{tid}/presentation').json()
        assert len(p['stages'])==9
        assert all(b['state'] in {'pending','waiting','running','completed','partial','cancelled','skipped','unknown'} for st in p['stages'] for b in st['blocks'])
        assert p['stages'][0]['blocks'][2]['state']=='pending'
        assert p['delivery_ref'] is None
        assert p['materials']==[]
        assert client.get(f'/api/tasks/{tid}/execution').status_code==200
        after=client.get(f'/api/tasks/{tid}/state').json()
        assert before['revision']==after['revision'] and before['core_event_cursor']==after['core_event_cursor']
        with app.repository.read() as c:assert c.execute('SELECT count(*) FROM attempts').fetchone()[0]==0

def test_historical_projection_excludes_future_materials_and_delivery(tmp_path):
    api=create_app(tmp_path,start_worker=False);app=api.state.application
    task=app.create('SYNTHETIC historical request',str(uuid4()));tid=task['task_id'];repo=app.repository
    with repo.transaction() as c:
        repo.put_object(c,tid,'material_preparation','materials',1,{'revision':1,'closed':False,'pools':{'p':{'acquired':['w1'],'evaluated':['w1']}}})
        old=repo.event(c,tid,'ui_fixture_milestone',{})
    with repo.transaction() as c:
        repo.put_object(c,tid,'material_preparation','materials',2,{'revision':2,'closed':True,'pools':{'p':{'acquired':['w1','w2'],'evaluated':['w1','w2']}}})
        repo.event(c,tid,'delivery_ready',{'delivery_ref':{'id':'synthetic','version':1}})
    p=presentation(app,tid,old['seq']);latest=presentation(app,tid)
    assert p['materials'][0]['readable']==1 and latest['materials'][0]['readable']==2
    assert p['delivery_ref'] is None and latest['delivery_ref']['id']=='synthetic'
    assert p['counts']['records']==0

def test_list_groups_filter_before_pagination_and_exclude_replays_on_request(tmp_path):
    api=create_app(tmp_path,start_worker=False);app=api.state.application;repo=app.repository
    a=app.create('SYNTHETIC waiting',str(uuid4()));b=app.create('SYNTHETIC completed',str(uuid4()))
    with repo.transaction() as c:
        c.execute("UPDATE tasks SET lifecycle='waiting_input' WHERE task_id=?",(a['task_id'],))
        c.execute("UPDATE tasks SET lifecycle='completed' WHERE task_id=?",(b['task_id'],))
    with TestClient(api) as client:
        body=client.get('/api/tasks?category=attention&limit=1&include_replays=false').json()
        assert body['total']==1 and body['items'][0]['task_id']==a['task_id']
        assert client.get('/api/tasks?category=not-a-category').status_code==422
        assert client.get(f"/api/tasks/{a['task_id']}/presentation?at_seq=9999").status_code==422

def test_config_reports_effective_sort_without_credentials(tmp_path):
    with TestClient(create_app(tmp_path,start_worker=False)) as client:
        body=client.get('/api/config').json()
        assert body['effective_values']['ads_sort']=='score desc'
        assert 'dashscope_api_key' not in body['editable_values']
        assert 'ads_api_token' not in body['editable_values']

def test_diagnostic_redaction():
    assert 'private-key' not in redacted('api_key=private-key&x=1')
    assert 'private-token' not in redacted('Bearer private-token')

def test_provisional_ui_view_preserves_raw_cells_without_advancing_task(tmp_path):
    import asyncio
    from tests.rebuild.scenario import application, confirmed_case
    app=application(tmp_path)
    def stop_before_seal(scheduler):
        async def fixture_boundary(job):
            pass
        scheduler.handlers['finalize']=fixture_boundary
    # UI-only boundary fixture. Earlier records are produced by the normal
    # synthetic chain; a terminal snapshot is never reopened or rewritten.
    state,_=asyncio.run(confirmed_case(app,setup_scheduler=stop_before_seal))
    api=create_app(tmp_path,application=app,allow_synthetic=True,start_worker=False)
    with TestClient(api) as client:
        tid=state['task_id'];before=client.get(f'/api/tasks/{tid}/state').json()
        raw=client.get(f'/api/tasks/{tid}/preview').json()
        ui=client.get(f'/api/tasks/{tid}/preview?view=ui').json()
        assert ui['preview_id']==raw['preview_id'] and ui['counts']==raw['counts']
        assert ui['items'][0]['source']==raw['items'][0]['source']
        cell=next(c for v in ui['items'][0]['evidence_views'] for c in v.get('cells',[]) if c['is_main'])
        assert cell['raw']=='0' and cell['column']=='Length'
        after=client.get(f'/api/tasks/{tid}/state').json()
        assert before['revision']==after['revision'] and before['core_event_cursor']==after['core_event_cursor']

def test_library_status_read_does_not_claim_missing_libraries_are_loaded(tmp_path):
    with TestClient(create_app(tmp_path,start_worker=False)) as client:
        status=client.get('/api/library-status').json()
        assert status['registry']['state']=='unavailable'
        assert status['knowledge_bindings']['state']=='unavailable'

def test_exports_after_terminal_do_not_extend_original_run_duration(tmp_path):
    api=create_app(tmp_path,start_worker=False);app=api.state.application
    task=app.create('SYNTHETIC duration',str(uuid4()));tid=task['task_id']
    with app.repository.transaction() as conn:app.repository.mutate_task(conn,tid,lifecycle='completed')
    before=presentation(app,tid)
    with app.repository.transaction() as conn:app.repository.event(conn,tid,'export_ready',{'ui_fixture':True})
    after=presentation(app,tid)
    assert before['wall_seconds']==after['wall_seconds']
    assert before['terminal_at']==after['terminal_at'] and after['cursor']>before['cursor']
    from astroquery_ai.application.presentation import replay_clock
    clock=replay_clock(app,tid)
    assert clock['timeline'][-1]['seq']==before['cursor']
    assert clock['terminal_at']==before['terminal_at']
    assert presentation(app,tid,clock['timeline'][-1]['seq'])['lifecycle']=='completed'
    from astroquery_ai.application.presentation import execution
    playback=execution(app,tid)
    assert playback['created_at']==after['created_at'] and playback['terminal_at']==after['terminal_at']

def test_ready_without_actual_change_event_is_not_a_data_modification():
    from astroquery_ai.application.result_views import changes
    body={'measurements':[{'measurement_id':'SYNTHETIC','property_ref':{'id':'p'}}],
          'derived':[{'derived_id':'d','measurement_id':'SYNTHETIC','main_state':'ready'}],
          'provenance_bundle':{}}
    assert changes(body)==[]

def test_old_review_wording_is_not_borrowed_from_later_revision(tmp_path):
    import asyncio
    from tests.rebuild.scenario import application, confirmed_case
    from astroquery_ai.runtime.codec import canonical
    app=application(tmp_path);state,_=asyncio.run(confirmed_case(app,ambiguous=True))
    tid=state['task_id'];cursor=state['core_event_cursor'];review=state['reviews'][0]
    changed={k:v for k,v in review.items() if k not in {'evidence_bundle','answer','application'}}
    changed.update(revision=2,question='SYNTHETIC FUTURE wording')
    with app.repository.transaction() as conn:
        conn.execute('UPDATE reviews SET revision=2,payload=? WHERE review_id=?',(canonical(changed),review['review_id']))
        app.repository.event(conn,tid,'review_ready',{'review_id':review['review_id'],'revision':2})
    past=presentation(app,tid,cursor)['reviews'][0]
    assert 'FUTURE' not in past['question'] and '未保存' in past['question']
    assert past['evidence']==[] and past['answer'] is None
