"""Chat projections are read-only views of actual persisted events and versions."""
from uuid import uuid4
from astroquery_ai.api.http import create_app
from astroquery_ai.application.presentation import presentation, replay_clock


def test_delivery_summary_uses_the_visible_sealed_revision(tmp_path):
    app=create_app(tmp_path,start_worker=False).state.application
    tid=app.create("SYNTHETIC summary",str(uuid4()))["task_id"]
    repo=app.repository
    with repo.transaction() as c:
        for i in range(3):
            repo.put_object(c,tid,"measurement",str(i),1,{"measurement_id":str(i)})
        body={"delivery_id":"d","revision":1,"measurements":[{"measurement_id":"0"}],
              "sources":[],"figures":[],"definitions":[],"snapshot_ref":{"id":"s","version":1},
              "task_score":{"score":None,"status":"pending"},"insight_report":{}}
        repo.put_object(c,tid,"delivery","d",1,body)
        old=repo.event(c,tid,"delivery_ready",{"delivery_ref":{"id":"d","version":1}})
    with repo.transaction() as c:
        body={**body,"revision":2,"task_score":{"score":88,"status":"available"},
              "insight_report":{"qualified_property_ids":["p"]}}
        repo.put_object(c,tid,"delivery","d",2,body)
        repo.event(c,tid,"delivery_ready",{"delivery_ref":{"id":"d","version":2}})
    past=presentation(app,tid,old["seq"])
    current=presentation(app,tid)
    assert past["counts"]["records"]==3
    assert past["delivery_summary"]["records"]==1
    assert past["delivery_summary"]["score"] is None
    assert past["delivery_summary"]["insights"]==0
    assert current["delivery_summary"]["score"]==88
    assert current["delivery_summary"]["insights"]==1


def test_chat_activity_only_uses_objects_visible_at_cursor(tmp_path):
    app=create_app(tmp_path,start_worker=False).state.application
    tid=app.create("SYNTHETIC activity",str(uuid4()))["task_id"]
    with app.repository.transaction() as c:
        app.repository.put_object(c,tid,"catalog_pool","pool",1,
            {"discovered_resources":["r"],"discovered_tables":["r/a"],"closed":False})
        old=app.repository.event(c,tid,"ui_fixture_milestone",{})
    with app.repository.transaction() as c:
        app.repository.put_object(c,tid,"catalog_pool","pool",2,
            {"discovered_resources":["r","future"],"discovered_tables":["r/a","future/b"],"closed":True})
        app.repository.event(c,tid,"ui_fixture_milestone",{})
    with app.repository.read() as c:
        before=c.execute("SELECT revision,last_event_seq FROM tasks WHERE task_id=?",(tid,)).fetchone()
    p=presentation(app,tid,old["seq"],True)
    assert p["chat_activity"]["catalog"]["tables"]==1
    assert p["chat_activity"]["catalog"]["resources"]==1
    assert not p["chat_activity"]["catalog"]["closed"]
    assert "chat_activity" not in presentation(app,tid)
    with app.repository.read() as c:
        after=c.execute("SELECT revision,last_event_seq FROM tasks WHERE task_id=?",(tid,)).fetchone()
    assert tuple(before)==tuple(after)


def test_replay_choice_requires_revision_and_basis_match_and_stays_separate(tmp_path):
    app=create_app(tmp_path,start_worker=False).state.application
    tid=app.create("SYNTHETIC review",str(uuid4()))["task_id"]
    with app.repository.transaction() as c:
        q=app.repository.event(c,tid,"review_ready",{"review_id":"r","revision":1})
        a=app.repository.event(c,tid,"answer_received",{"review_id":"r","answer_id":"a"})
    review={"review_id":"r","revision":1,"basis_hash":"b",
            "answer":{"answer_id":"a","basis_hash":"b","action":"confirm","reason":"must not leak future explanation"}}
    app.reviews.list=lambda *args:[review]
    clock=replay_clock(app,tid)
    gate=clock["review_gates"][0]
    assert gate["available"] and gate["question_seq"]==q["seq"] and gate["answer_seq"]==a["seq"]
    assert gate["answer"]["action"]=="confirm" and "reason" not in gate["answer"]
    review["revision"]=2
    assert not replay_clock(app,tid)["review_gates"][0]["available"]
    review["revision"]=1
    review["answer"]["basis_hash"]="other"
    assert not replay_clock(app,tid)["review_gates"][0]["available"]


def test_repeated_catalog_jobs_do_not_become_distinct_tables():
    from astroquery_ai.application.chat_activity import project
    jobs={str(i):{"kind":"catalog_extract","status":"succeeded","payload":{"table_id":"same"}} for i in range(4)}
    p=project(lambda kind:[],jobs,[],cursor=4)
    assert p["catalog"]["deep_checks"]["total"]==1
    assert len(p["catalog"]["items"])==1
    assert p["papers"]["readable"] is None


def test_attachment_source_resolves_to_original_file_and_parent():
    from astroquery_ai.application.chat_activity import project
    data={"attachment":[{"attachment_id":"a","table_id":"a/table","work_id":"w",
        "original_filename":"original.dat","artifact":{"artifact_id":"bytes"}}],
        "source":[{"source_id":"s","kind":"official_attachment","table_id":"a/table","work_id":"w",
                   "title":"Generic extracted cells","artifact":{"artifact_id":"bytes"}}],
        "work":[{"work_id":"w","records":[{"title":"Actual parent paper"}]}]}
    p=project(lambda kind:data.get(kind,[]),{},[],cursor=1)
    files=p["attachments"]["items"]
    assert len(files)==1
    assert files[0]["label"]=="original.dat"
    assert files[0]["parent_title"]=="Actual parent paper"
    assert files[0]["state"]=="readable"

def test_normal_http_draft_confirmation_and_review_answer_use_existing_versions(tmp_path):
    import asyncio
    from copy import deepcopy
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from tests.rebuild.scenario import application, run_until_wait
    from astroquery_ai.runtime.scheduler import Scheduler
    from astroquery_ai.runtime.run_policy import LEGACY_RUN_POLICY

    app=application(tmp_path)
    app.models.ambiguous=True
    scheduler=Scheduler(app)
    api=create_app(tmp_path,application=app,allow_synthetic=True,start_worker=False)
    with TestClient(api) as client:
        created=client.post("/api/tasks",json={"query":"SYNTHETIC_AQ 测试长度","operation_id":str(uuid4())})
        assert created.status_code==200
        tid=created.json()["task_id"]
        asyncio.run(run_until_wait(app,scheduler))
        state=client.get(f"/api/tasks/{tid}/state").json()
        preview=state["pending"]["preview"]
        with patch("astroquery_ai.runtime.run_policy.request_policy",return_value=deepcopy(LEGACY_RUN_POLICY)):
            response=client.post(f"/api/tasks/{tid}/draft-actions",json={
                "protocol_version":2,"operation_id":str(uuid4()),"expected_revision":state["revision"],
                "question_id":state["pending"]["question_id"],"action":{"type":"confirm","preview_hash":preview["preview_hash"]}})
        assert response.status_code==200
        asyncio.run(run_until_wait(app,scheduler))
        state=client.get(f"/api/tasks/{tid}/state").json()
        review=next(r for r in state["reviews"] if r["status"]=="pending")
        answer={"task_id":tid,"review_id":review["review_id"],"review_revision":review["revision"],
            "basis_hash":review["basis_hash"],"client_request_id":str(uuid4()),"action":"unable","reason":""}
        assert client.post(f"/api/tasks/{tid}/review-answers",json=answer).status_code==200
        # Reading the answer alone must not impersonate successful owner application.
        shown=client.get(f"/api/tasks/{tid}/presentation?include_chat_activity=true").json()
        assert shown["reviews"][0]["status"]=="accepted"
        asyncio.run(run_until_wait(app,scheduler))
        after=client.get(f"/api/tasks/{tid}/presentation?include_chat_activity=true").json()
        assert after["reviews"][0]["answer"]["action"]=="unable"
        assert after["review_receipts"]

def test_candidate_status_uses_later_verdict_without_rewriting_original():
    from astroquery_ai.application.chat_activity import project
    candidate={"candidate_id":"c","state":"review_candidate","proposal":{"property_id":"p"}}
    data={"candidate":[candidate]}
    get=lambda kind:data.get(kind,[])
    events=[{"kind":"execution_stage_changed","payload":{"stage_id":"quality"}}]
    pending=project(get,{},events,cursor=1)
    assert pending["candidates"]["items"][0]["state"]=="collected"
    data["quality_decision"]=[{"root_id":"r","candidate_ref":{"id":"c"},"state":"supported"}]
    checked=project(get,{},events,cursor=2)
    assert checked["candidates"]["items"][0]["state"]=="supported"
    assert candidate["state"]=="review_candidate"
    assert checked["candidates"]["items"][0]["reported_state"]=="review_candidate"


def test_reextraction_shows_latest_leaf_verdicts_and_quality_revisits():
    from astroquery_ai.application.chat_activity import project
    data={"candidate":[{"candidate_id":"parent","state":"review_candidate","proposal":{}},
                       {"candidate_id":"child","state":"review_candidate","proposal":{}}],
          "quality_candidate_link":[{"root_id":"r","candidate_ref":{"id":"parent"},"parent_ref":None},
                                    {"root_id":"r","candidate_ref":{"id":"child"},"parent_ref":{"id":"parent"}}],
          "quality_reextraction_action":[{"root_id":"r","parent_candidate_ref":{"id":"parent"}}],
          "quality_reextraction_result":[{"root_id":"r","complete":True,"outcome":"recheck_pending","candidate_count":1}]}
    get=lambda kind:data.get(kind,[])
    quality={"kind":"execution_stage_changed","payload":{"stage_id":"quality"}}
    next_stage={"kind":"execution_stage_changed","payload":{"stage_id":"normalization"}}
    pending=project(get,{},[quality],cursor=1)
    assert pending["quality"]["items"][0]["state"]=="recheck_pending"
    closed=project(get,{},[quality,next_stage],cursor=2)
    assert closed["quality"]["items"][0]["state"]=="recheck_incomplete"
    reopened=project(get,{},[quality,next_stage,quality],cursor=3)
    assert reopened["quality"]["items"][0]["state"]=="recheck_pending"
    data["quality_decision"]=[{"root_id":"r","candidate_ref":{"id":"child"},"state":"supported"}]
    done=project(get,{},[quality,next_stage],cursor=4)
    assert done["quality"]["items"][0]["state"]=="rechecked"
    assert done["quality"]["items"][0]["reported_outcome"]=="recheck_pending"
    data["quality_decision"][0]["state"]="technical_failure"
    assert project(get,{},[quality,next_stage],cursor=5)["quality"]["items"][0]["state"]=="recheck_incomplete"


def test_closed_materials_keep_unused_backups_out_of_waiting_state():
    from astroquery_ai.application.chat_activity import project
    data={"work":[{"work_id":"backup","records":[]}],
          "material_preparation":[{"closed":False,"pools":{"p":{"eligible":["backup"]}}}]}
    get=lambda kind:data.get(kind,[])
    assert project(get,{},[],cursor=1)["papers"]["items"][0]["state"]=="eligible"
    data["material_preparation"][0]["closed"]=True
    assert project(get,{},[],cursor=2)["papers"]["items"][0]["state"]=="backup_unused"


def test_cancelled_reading_ends_its_display_without_claiming_job_success():
    from astroquery_ai.application.chat_activity import project
    jobs={"j":{"kind":"paper_batch","status":"running","payload":{"work_id":"w"}}}
    events=[{"kind":"task_state_changed","payload":{"lifecycle":"cancelled"}}]
    p=project(lambda kind:[],jobs,events,cursor=1)
    reading=p["reading"]
    assert reading["items"][0]["display_state"]=="ended_incomplete"
    assert reading["items"][0]["state"]=="running"
    assert reading["succeeded"]==0 and reading["finished"]==0
