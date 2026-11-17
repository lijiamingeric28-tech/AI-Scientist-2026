"""Title provenance regression uses real persistence and HTTP projections."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from astroquery_ai.api.http import create_app
from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.task_titles import title_origin


@pytest.mark.parametrize('question', ['查 HD 209458 的有效温度。', '中'*120, '中'*121,
                                     '长中文需求'*40, '🌟'*119+'🪐研究测量', 'SN 2014J '+ 'x'*94])
def test_default_title_read_identically_in_all_views(tmp_path, question):
    app = Application(tmp_path)
    task = app.create(question, str(uuid4()))
    tid = task['task_id']
    with TestClient(create_app(tmp_path, application=app, start_worker=False)) as client:
        for view in [None, 'chat', 'conversation', 'workspace']:
            result = client.get(f'/api/tasks/{tid}/state', params={'view': view} if view else {}).json()
            assert result['title_origin'] == 'auto'
            assert result['title'] == question[:120]
        listed = next(t for t in client.get('/api/tasks').json()['items'] if t['task_id'] == tid)
        assert listed['title_origin'] == 'auto'
    with app.repository.read() as conn:
        assert app.repository.objects(conn, tid, 'message')[0]['text'] == question


@pytest.mark.parametrize('name', ['人工设定的标题', '中'*120])
def test_manual_title_including_original_prefix_survives_refresh(tmp_path, name):
    app = Application(tmp_path)
    task = app.create('中'*140, str(uuid4()))
    result = app.maintenance.rename(task['task_id'], name)
    assert result['title_origin'] == 'custom'
    reopened = Application(tmp_path)
    assert reopened.view(task['task_id'], for_chat=True)['title_origin'] == 'custom'
    assert reopened.view(task['task_id'], for_workspace=True)['title'] == name
    with reopened.repository.read() as conn:
        assert title_origin(conn, reopened.repository.task(conn, task['task_id'])) == 'custom'


def test_old_nondefault_title_without_event_is_preserved(tmp_path):
    app = Application(tmp_path)
    task = app.create('SYNTHETIC original question', str(uuid4()))
    with app.repository.transaction() as conn:
        conn.execute('UPDATE tasks SET title=? WHERE task_id=?', ('historic name', task['task_id']))
    assert app.view(task['task_id'])['title_origin'] == 'custom'


def test_manual_title_survives_replay(tmp_path):
    app = Application(tmp_path)
    task = app.create('SYNTHETIC original query', str(uuid4()))
    app.maintenance.rename(task['task_id'], '手动历史名称')
    with app.repository.transaction() as conn:
        app.repository.mutate_task(conn, task['task_id'], lifecycle='cancelled')
    replay = app.history.replay(task['task_id'], 1, str(uuid4()))
    result = app.view(replay['task_id'])
    assert '手动历史名称' in result['title']
    assert result['title_origin'] == 'custom'
