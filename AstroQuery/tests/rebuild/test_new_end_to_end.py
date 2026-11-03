"""Fresh synthetic complete-path integration; not real scientific accuracy."""

import asyncio
from uuid import uuid4

import httpx

from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.codec import canonical, loads
from astroquery_ai.runtime.scheduler import Scheduler
from tests.rebuild.registry_fixture import make_release

XML_HEADER = b"""<?xml version="1.0"?><VOTABLE><RESOURCE name="J/SYNTHETIC/v1"><DESCRIPTION>SYNTHETIC software test only</DESCRIPTION><TABLE name="J/SYNTHETIC/v1/measurements"><FIELD name="Name" datatype="char" arraysize="*"><DESCRIPTION>Full object identifier</DESCRIPTION></FIELD><FIELD name="Length" datatype="double" unit="m"><DESCRIPTION>Synthetic whole length</DESCRIPTION></FIELD>"""


class SyntheticModels:
    async def json(self, *, owner, **kwargs):
        if owner == "M01":
            if kwargs['profile'].operation == 'property_selection':
                prompt=loads(kwargs['messages'][-1]['content'])
                pid=prompt['allowed_candidate_ids'][0]
                return {'property_operation': 'replace', 'clarification_needed': False,
                    'requests': [{'text': '测试长度', 'start': 13, 'end': 17,
                        'coverage': 'complete', 'gap': '', 'candidate_property_ids': [pid],
                        'equivalent_property_ids': [pid], 'explanation': 'SYNTHETIC registered whole length'}],
                    'conditions': [], 'unknown_fragments': []}, {'attempt_id': 'synthetic-semantic-selection'}
            result = {
                "targets": [{"text": "SYNTHETIC_AQ", "start": 0, "end": 12}],
                "properties": [{"text": "测试长度", "start": 13, "end": 17}],
                "conditions": [],
                "unknown_fragments": [],
                "property_operation": "replace",
                "clarification_needed": False,
            }
        elif owner == 'M04':
            prompt=loads(kwargs['messages'][-1]['content'])
            if kwargs['profile'].version == 'metadata-terms-2':
                return {'target_name_labels': [next(iter(prompt['verified_names']))],
                        'core_terms': ['length'], 'synonyms': [], 'method_terms': [],
                        'intent': 'SYNTHETIC only', 'rewrite_useful': False}, {'attempt_id': 'synthetic-metadata-terms'}
            if kwargs['profile'].version in {'literature-terms-1','literature-terms-2'}:
                return {'target_name_labels':[next(iter(prompt['verified_names']))],
                        'quantity_phrases':['synthetic whole length'],'intent':'SYNTHETIC finite material retrieval'}, {'attempt_id':'synthetic-terms-v2'}
            if kwargs['profile'].version in {'literature-query-4', 'literature-query-5'}:
                return {'query':'abs:("SYNTHETIC_AQ") AND (abs:(length) OR body:(length))',
                        'intent':'SYNTHETIC exact property retrieval'}, {'attempt_id':'synthetic-query-v4'}
            if kwargs['profile'].version == 'literature-query-3':
                prompt = next(loads(m['content']) for m in kwargs['messages'] if m['role'] == 'user' and 'verified_names' in loads(m['content']))
            if 'verified_names' in prompt:
                name = prompt['verified_names'][0]
                target = 'abs:("' + name['name'] + '")'
                result = {'queries': [dict(family=f['id'], properties=f['properties'], channel=channel,
                    names=[name['id']], target_query=target,
                    quantity_query=('body' if channel == 'body' else 'abs') + ':(length)',
                    query='(' + target + ') AND (' + ('body' if channel == 'body' else 'abs') + ':(length))',
                    intent='SYNTHETIC whole length retrieval')
                    for f in prompt['families'] for channel in ('metadata', 'body')]}
            else:
                result={'works':[{'id':w['id'],'decision':'needs_fulltext',
                    'properties':[b['property_id'] for b in prompt['properties']],
                    'evidence':[],'reason':'SYNTHETIC metadata needs fulltext'} for w in prompt['works']]}
        elif owner == "M03":
            prompt = loads(kwargs["messages"][-1]["content"])
            if kwargs['profile'].operation == 'catalog_select':
                if 'metadata' not in prompt:
                    result = {'queries': ['SYNTHETIC catalogue length']}
                else:
                    result = {'candidates': [{'node_id': c['node_id'],
                        'property_ids': [b['property_id'] for b in prompt['properties']], 'priority': 3,
                        'evidence_quote': c.get('native_source_label') or c['description'], 'object_hint': None} for c in prompt['metadata']]}
                return result, {'attempt_id': 'synthetic-not-a-provider-attempt', 'usage': None}
            if "rows" not in prompt:
                result = {
                    "id_column": "Name",
                    "identity_namespace": None,
                    "properties": [
                        {
                            "property_id": "synthetic-length",
                            "value_column": "Length",
                            "error_columns": [],
                            "source_unit": "m",
                            "source_representation": "linear",
                        }
                    ],
                    "limitations": [],
                }
            else:
                result = {
                    "coverage": "checked",
                    "limitations": [],
                    "results": [
                        {
                            "property_id": "synthetic-length",
                            "value": {"kind": "real", "value": "0"},
                            "raw_value": "0",
                            "unit": "m",
                            "representation": "linear",
                            "source_quote": "SYNTHETIC_AQ 0 m",
                            "page": None,
                            "row": 0,
                            "column": "Length",
                            "subject_role": "target",
                            "result_role": "reported_result",
                            "location_kind": "catalog_cell",
                            "limit": "none",
                            "errors": [],
                            "conditions": [],
                            "ambiguity": None,
                        }
                    ],
                }
        else:
            raise AssertionError("identity normalization must not require another model")
        return result, {"attempt_id": "synthetic-not-a-provider-attempt", "usage": None}


class SyntheticIdentity:
    def __init__(self, app):
        self.app = app

    async def resolve(self, task_id, mention):
        artifact = self.app.artifacts.write(b"SYNTHETIC identity fixture", "application/json")
        target = {
            "schema_version": "VerifiedTarget/2",
            "target_id": "synthetic-target",
            "authority": "SIMBAD",
            "main_id": "SYNTHETIC_AQ",
            "primary_otype": "pA*",
            "aliases": ["SYNTHETIC_AQ"],
            "coordinates": {"ra_deg": 0, "dec_deg": 0, "frame": "ICRS", "epoch": None},
            "submitted_mentions": [mention],
            "resolution_method": "exact_name",
            "evidence_id": "synthetic-identity",
            "retrieved_at": "2026-10-25T00:00:00+00:00",
            "raw_type_fields": {"otype": "pA*"},
            "classification_assertions": [],
            "classification_completeness": {
                "primary": "verified",
                "secondary": "not_returned",
                "adapter_capabilities": [],
                "adapter_version": "synthetic",
            },
        }
        return {
            "state": "matched",
            "targets": [target],
            "artifact": artifact,
            "metadata": {"retrieved_at": target["retrieved_at"]},
        }


def test_new_synthetic_full_flow_confirm_sources_quality_delivery_export(tmp_path, monkeypatch):
    from copy import deepcopy
    from astroquery_ai.runtime import run_policy
    monkeypatch.setattr(run_policy, 'request_policy', lambda _, preferences=None: deepcopy(run_policy.LEGACY_RUN_POLICY))
    async def run():
        app = Application(tmp_path / "data", allow_synthetic=True)
        package = tmp_path / "new-synthetic-registry"
        make_release(package)
        app.registry.import_release(package)
        app.models = SyntheticModels()
        app.identity = SyntheticIdentity(app)
        app.configuration.runtime["ads_api_token"] = "SYNTHETIC-NOT-A-REAL-TOKEN"
        with app.repository.transaction() as conn:
            for owner in ("M01", "M03", "M06", "M08"):
                conn.execute(
                    "INSERT INTO settings VALUES(?,?,1)",
                    ("profile:" + owner, canonical({"state": "validated", "synthetic": True})),
                )

        def handle(request):
            if request.url.host in {'cdsarc.cds.unistra.fr', 'vizier.cfa.harvard.edu'} and request.url.path.endswith('/ReadMe'):
                return httpx.Response(404, text='SYNTHETIC: no ReadMe')
            if request.url.host == "api.adsabs.harvard.edu":
                return httpx.Response(200, json={"response": {"numFound": 0, "docs": []}})
            if request.url.host in {"vizier.cds.unistra.fr", "vizier.idia.ac.za", "vizier.cfa.harvard.edu"}:
                values = dict(request.url.params)
                table_data = (
                    b"<DATA><TABLEDATA><TR><TD>SYNTHETIC_AQ</TD><TD>0</TD></TR></TABLEDATA></DATA>"
                    if "Name" in values
                    else b""
                )
                return httpx.Response(
                    200, content=XML_HEADER + table_data + b"</TABLE></RESOURCE></VOTABLE>"
                )
            raise AssertionError("unexpected network")

        app.http.transport = httpx.MockTransport(handle)
        scheduler = Scheduler(app)
        task = app.create("SYNTHETIC_AQ 测试长度", str(uuid4()))
        first = app.repository.claim_job(scheduler.owner_id, lease_seconds=600)
        await scheduler.dispatch(first)
        selection = app.repository.claim_job(scheduler.owner_id, lease_seconds=600)
        assert selection['owner'] == 'M01' and selection['payload']['selection_only']
        await scheduler.dispatch(selection)
        state = app.view(task["task_id"])
        assert state["pending"]["kind"] == "final_confirmation"
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
        count = 0
        while job := app.repository.claim_job(scheduler.owner_id, lease_seconds=600):
            count += 1
            assert count < 40, "finite jobs must converge, not loop"
            await scheduler.dispatch(job)
        state = app.view(task["task_id"])
        assert state["lifecycle"] == "completed" and state["science_state"] == "sealed"
        with app.repository.read() as conn:
            delivery = app.delivery.get(conn, task["task_id"])
            assert len(delivery["measurements"]) == 1
            assert delivery["measurements"][0]["value"]["value"] == "0"
            report_ref = delivery["quality"]["report_ref"]
            quality = app.repository.object(conn, task["task_id"], "quality", report_ref["id"])
            assert quality["overall_score"] is None  # no source-quality check in this fixture
            assert quality["measurements"][0]["delivery"] == 100
            assert quality["input_ref"] == delivery["snapshot_ref"]
            receipts = delivery['provenance_bundle']['processing_receipts']
            assert len(receipts) == 1 and receipts[0]['postcheck'] == 'passed'
            assert receipts[0]['input_ref']['content_sha256'] == delivery['measurements'][0]['content_sha256']
            assert receipts[0]['output_ref']['id'] == delivery['derived'][0]['derived_id']
        exported = app.delivery.export(
            task["task_id"],
            {
                "operation_id": str(uuid4()),
                "task_id": task["task_id"],
                "delivery_id": delivery["delivery_id"],
                "expected_delivery_revision": 1,
                "selection": {"mode": "all", "measurement_ids": []},
                "format": "json",
                "export_schema_version": 1,
            },
        )
        artifact, path = app.artifacts.read_owned(
            task["task_id"], exported["artifacts"][0]["artifact_id"]
        )
        exported_json = loads(path.read_bytes())
        assert exported_json["measurements"][0]["value"]["value"] == "0"
        assert exported_json['provenance_bundle']['processing_receipts'] == receipts
        assert app.budget.summary()["actual_micros"] == 0

    asyncio.run(run())
