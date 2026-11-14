import json
import pytest
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.agent_harness.store import AgentStore

SCOPE = {'delivery_id':'delivery-a','delivery_revision':2,
         'snapshot_ref':{'id':'science-a','version':1,'content_sha256':'a'*64}}

def source(tmp_path):
    repo=Repository(tmp_path/'source.sqlite3')
    repo.create_task('demo',task_id='demo')
    store=AgentStore(repo)
    with repo.transaction() as c:
        for role,mid in [('user','question'),('assistant','answer')]:
            c.execute('INSERT INTO agent_messages (id,task_id,role,content,created_at,scope,question_id,status,answer,citations,meta,thought_steps) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (mid,'demo',role,'public text','2026-11-14T00:00:00Z',json.dumps(SCOPE),'question' if role=='assistant' else None,'complete',
                 json.dumps({'blocks':[{'id':'text','type':'text','markdown':'a saved answer','refs':[]}]} ) if role=='assistant' else None,
                 '[]',json.dumps({'context':{'secret':'private input'},'operation':'private','model':'actual-model','elapsed_seconds':3}),
                 '[{"thought":"private reasoning"}]'))
    return repo

def test_public_messages_keep_real_answer_and_exact_scope_but_remove_private_inputs(tmp_path):
    from astroquery_ai.runtime.demo_messages import public_messages
    repo=source(tmp_path)
    with repo.read() as c: rows=public_messages(c,'demo',SCOPE)
    assert [r['id'] for r in rows]==['question','answer']
    assert rows[1]['answer'] and json.loads(rows[1]['scope'])==SCOPE
    assert json.loads(rows[1]['meta'])=={'model':'actual-model','elapsed_seconds':3}
    assert json.loads(rows[1]['thought_steps'])==[]
    assert 'private' not in json.dumps(rows)

def test_public_messages_omit_incomplete_and_other_revision_answers(tmp_path):
    from astroquery_ai.runtime.demo_messages import public_messages
    repo=source(tmp_path)
    with repo.transaction() as c:c.execute("UPDATE agent_messages SET status='interrupted' WHERE id='answer'")
    with repo.read() as c:assert public_messages(c,'demo',SCOPE)==[]
    with repo.transaction() as c:c.execute("UPDATE agent_messages SET status='complete' WHERE id='answer'")
    with repo.read() as c:assert public_messages(c,'demo',{**SCOPE,'delivery_revision':3})==[]

def test_import_rejects_public_messages_with_private_state(tmp_path):
    from astroquery_ai.runtime.demo_messages import validate_public_message
    repo=source(tmp_path)
    with repo.read() as c: row=dict(c.execute("SELECT * FROM agent_messages WHERE id='answer'").fetchone())
    with pytest.raises(ValueError):validate_public_message(row,'demo',SCOPE['snapshot_ref'])

def test_installed_demo_receives_public_answers_once_without_overwriting_local_versions(tmp_path):
    from types import SimpleNamespace
    from astroquery_ai.runtime.published_demos import PublishedDemos
    from astroquery_ai.runtime.demo_messages import public_messages
    repo=source(tmp_path)
    with repo.read() as c:rows=public_messages(c,'demo',SCOPE)
    with repo.transaction() as c:
        c.execute('DELETE FROM agent_messages')
        c.execute('UPDATE tasks SET delivery_ref=? WHERE task_id=?',(json.dumps({'id':'delivery-a','version':2}),'demo'))
        repo.put_object(c,'demo','task_origin','demo',1,{'source':'sample'})
    service=PublishedDemos(SimpleNamespace(repository=repo))
    service.index={'demo':{'snapshot_ref':SCOPE['snapshot_ref'],'public_messages':rows}}
    assert service.open('demo')
    with repo.transaction() as c:c.execute("UPDATE agent_messages SET content='local edit' WHERE id='answer'")
    service.loaded.clear()
    assert service.open('demo')
    with repo.read() as c:
        assert c.execute('SELECT count(*) FROM agent_messages').fetchone()[0]==2
        assert c.execute("SELECT content FROM agent_messages WHERE id='answer'").fetchone()[0]=='local edit'

def test_same_id_user_task_is_not_backfilled_from_demo(tmp_path):
    from types import SimpleNamespace
    from astroquery_ai.runtime.published_demos import PublishedDemos
    repo=source(tmp_path)
    service=PublishedDemos(SimpleNamespace(repository=repo))
    service.index={'demo':{'snapshot_ref':SCOPE['snapshot_ref'],'public_messages':[{}]}}
    assert service.open('demo') is False
