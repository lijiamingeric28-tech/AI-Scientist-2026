"""New synthetic browser/integration scenario. Never a production data package."""

import httpx
from uuid import uuid4

from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.scheduler import Scheduler
from tests.rebuild.registry_fixture import make_release
from tests.rebuild.test_new_end_to_end import SyntheticModels, SyntheticIdentity, XML_HEADER


class ScenarioModels(SyntheticModels):
    ambiguous = False

    async def json(self, **kwargs):
        response, receipt = await super().json(**kwargs)
        if kwargs["owner"] == "M03" and response.get("results") and self.ambiguous:
            response["results"][0]["ambiguity"] = (
                "SYNTHETIC审核场景：请核对该行是否为目标的已报告长度。"
            )
            response['results'][0]['catalog_review_issue'] = dict(
                issue_kind='quantity_semantics', issue_key='synthetic-whole-length-boundary',
                question='SYNTHETIC：所给列说明与整体性质边界存在争议，是否按原件纠正并纳入？',
                undecided_fact='SYNTHETIC whole-length boundary ambiguity.',
                scope_columns=['Length'], support_columns=['Length'], counter_columns=[],
                choices=[dict(action='correct', label='按所给原行纠正', impact='经原值及类型复检后纳入。'),
                         dict(action='unable', label='无法判断', impact='保留未决候选。')],
                correction_types=['correct_value'])
        return response, receipt


def application(root):
    app = Application(root, allow_synthetic=True)
    package = root / "synthetic-package"
    if not package.exists():
        make_release(package)
    app.registry.import_release(package)
    app.models, app.identity = ScenarioModels(), SyntheticIdentity(app)
    app.configuration.runtime["ads_api_token"] = "SYNTHETIC-NOT-A-REAL-TOKEN"
    with app.repository.transaction() as conn:
        for owner in ("M01", "M03", "M06", "M08"):
            conn.execute(
                "INSERT OR REPLACE INTO settings VALUES(?,?,1)",
                ("profile:" + owner, canonical({"state": "validated", "synthetic": True})),
            )

    def handle(request):
        if request.url.host in {'cdsarc.cds.unistra.fr','vizier.cfa.harvard.edu'} and request.url.path.endswith('/ReadMe'):
            return httpx.Response(404, text='SYNTHETIC scenario has no external ReadMe')
        if request.url.host == "api.adsabs.harvard.edu":
            return httpx.Response(200, json={"response": {"numFound": 0, "docs": []}})
        if request.url.host in {"vizier.cds.unistra.fr", "vizier.idia.ac.za", "vizier.cfa.harvard.edu"}:
            table_data = (
                b"<DATA><TABLEDATA><TR><TD>SYNTHETIC_AQ</TD><TD>0</TD></TR></TABLEDATA></DATA>"
                if "Name" in request.url.params
                else b""
            )
            return httpx.Response(
                200, content=XML_HEADER + table_data + b"</TABLE></RESOURCE></VOTABLE>"
            )
        raise AssertionError("Synthetic scenario forbids external network")

    app.http.transport = httpx.MockTransport(handle)
    return app


async def run_until_wait(app, scheduler):
    count = 0
    while job := app.repository.claim_job(scheduler.owner_id, lease_seconds=600):
        count += 1
        if count > 80:
            raise AssertionError("scenario did not converge")
        await scheduler.dispatch(job)


async def confirmed_case(app, *, ambiguous=False, setup_scheduler=None, run_policy=None):
    app.models.ambiguous = ambiguous
    scheduler = Scheduler(app)
    if setup_scheduler:
        setup_scheduler(scheduler)
    task = app.create("SYNTHETIC_AQ 测试长度", str(uuid4()))
    await run_until_wait(app, scheduler)
    state = app.view(task["task_id"])
    # This long-standing fixture tests the frozen legacy contract. New-flow
    # tests explicitly pass the new policy; no production API gains a bypass.
    from unittest.mock import patch
    from copy import deepcopy
    from astroquery_ai.runtime.run_policy import LEGACY_RUN_POLICY
    with patch('astroquery_ai.runtime.run_policy.request_policy',return_value=deepcopy(run_policy or LEGACY_RUN_POLICY)):
        app.draft_action(
            task["task_id"],
            {
                "protocol_version": 2,
                "operation_id": str(uuid4()),
                "expected_revision": state["revision"],
                "question_id": state["pending"]["question_id"],
                "action": {
                    "type": "confirm",
                    "preview_hash": state["pending"]["preview"]["preview_hash"],
                },
            },
        )
    await run_until_wait(app, scheduler)
    return app.view(task["task_id"]), scheduler


def synthetic_acquired_parent(scheduler):
    """Fixture acquisition boundary only; never scientific verification evidence."""
    from astroquery_ai.science.workflow.paper_service import PaperService
    from astroquery_ai.science.qualification import qualify_source
    app = scheduler.application
    service = next(s for s in scheduler.pipeline.services if isinstance(s, PaperService))
    async def acquire(job, selection, work):
        tid = job['task_id']
        artifact = app.artifacts.write(b'%PDF-SYNTHETIC boundary fixture, not a real paper', 'application/pdf')
        identity = {'state':'SYNTHETIC fixture identity only'}
        source, qualification = qualify_source({'source_id':work['work_id'], 'kind':'paper',
            'work':work, 'artifact':artifact, 'identity':identity, 'title':['SYNTHETIC parent'],
            'version_grade':'unknown'}, identity=identity, checked_scope=['SYNTHETIC acquisition boundary'])
        with app.repository.transaction() as conn:
            app.repository.validate_lease(conn, job)
            app.artifacts.register(conn, tid, work['work_id'], artifact)
            app.repository.put_object(conn, tid, 'qualification', qualification['qualification_id'], 1, qualification)
            from astroquery_ai.science.literature_preparation import enabled
            if enabled(service.spec(conn, tid)):
                app.repository.put_object(conn, tid, 'prepared_source', work['work_id'], 1, source)
                app.repository.put_object(conn, tid, 'document_index', work['work_id'], 1,
                                          {'pages': [], 'page_count': 0})
                app.repository.put_object(conn, tid, 'acquisition_result', work['work_id'], 1,
                                          {'work_id': work['work_id'], 'state': 'acquired'})
            else:
                app.repository.put_object(conn, tid, 'source', work['work_id'], 1, source)
                app.repository.enqueue(conn, tid, 'M05', 'attachment_discover', {'work_id':work['work_id']})
    service.acquire_one = acquire
