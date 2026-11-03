"""Reading aids must never promote an ambiguous excerpt or a later document revision."""
import json
import sqlite3

import pymupdf
import pytest

from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.documents import page_image
from astroquery_ai.science.evidence_views import focus_record_views


@pytest.mark.parametrize('lines,raw,marked', [
    (['A', '9.80± 0.08'], '9.80±0.08', True),
    (['9.80', '9.80'], '9.80', False),
    (['19.80', '9.800'], '9.80', False),
    (['−9.80'], '9.80', False),
])
def test_value_focus_requires_one_native_occurrence_within_the_verified_box(lines, raw, marked):
    conn = sqlite3.connect(':memory:')
    conn.execute('create table objects(task_id,kind,object_id,version,created_at,payload)')
    bbox = [10,20,80,40]
    page = {'page': 1, 'width':100, 'height':200,
            'layout_lines':[{'text':s, 'bbox':bbox} for s in lines]}
    for version, date in [(1,'01'),(2,'03')]:
        index = {'sha256':'original','pages':[page if version == 1 else {**page,'layout_lines':[]}]}
        conn.execute("insert into objects values('t','document_index','w',?,?,?)",
                     (version, date, json.dumps(index)))
    view = {'kind':'pdf', 'artifact_ref':{'content_sha256':'original'},'points':[
        {'page':1, 'width':100,'height':200,'bbox':[bbox]}, {'page':1,'width':100,'height':200,'bbox':[]}]}
    points=focus_record_views(conn,'t','02',{'work_id':'w'},{'raw_value':raw},[view])[0]['points']
    assert ('value_line_bbox' in points[0]) is marked
    assert 'value_line_bbox' not in points[1] and 'value_line_bbox' not in view['points'][0]


def test_history_reader_does_not_require_or_recreate_a_draft(tmp_path):
    from astroquery_ai.runtime.application import Application
    app = Application(tmp_path)
    task = app.repository.create_task('保存的原始查询')
    for compact in (False, True):
        state = app.view(task['task_id'], for_conversation=compact)
        assert state['draft'] is None and state['pending'] is None
        assert state['messages'] and state['omission_context_hash'] is None
    with app.repository.read() as conn:
        assert not app.repository.objects(conn, task['task_id'], 'draft')


def test_history_opens_during_preflight_without_starting_scientific_jobs(tmp_path, monkeypatch):
    from threading import Event
    from fastapi.testclient import TestClient
    from astroquery_ai.api.http import create_app
    app = create_app(tmp_path)
    entered, release, started = Event(), Event(), Event()

    def warmup():
        entered.set()
        assert release.wait(5)

    async def start():
        started.set()

    monkeypatch.setattr(app.state.application.registry, 'load', warmup)
    monkeypatch.setattr(app.state.scheduler, 'start', start)
    with TestClient(app) as client:
        try:
            assert entered.wait(3)
            assert client.get('/api/health').json()['scientific_startup'] == 'preparing'
            assert client.get('/api/tasks').status_code == 200
            assert not started.is_set()
        finally:
            release.set()
        assert started.wait(3)
        assert client.get('/api/health').json()['scientific_startup'] == 'ready'


def test_oversize_original_can_be_viewed_entirely_without_lowering_science_resolution(tmp_path):
    path = tmp_path/'wide.pdf'
    with pymupdf.open() as doc:
        doc.new_page(width=1800, height=500)
        doc.save(path)
    with pytest.raises(DomainError, match='需分区'):
        page_image(path, 1)
    import struct
    width,height=struct.unpack('>II',page_image(path,1,display_only=True)[16:24])
    assert width <= 2049 and abs(width/height - 3.6) < .01
