"""SYNTHETIC qualifications in temporary repositories, never scientific approval."""

import asyncio
from dataclasses import replace

import httpx
import pytest

from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.calls import ModelProfile
from astroquery_ai.runtime.codec import canonical, content_hash, digest
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.codec import loads


def qualified_case(tmp_path):
    app = Application(tmp_path, allow_synthetic=True)
    app.configuration.runtime.update(
        dashscope_base_url="https://synthetic.example/v1",
        dashscope_api_key="SYNTHETIC-NEVER-TRANSMIT",
    )
    validation = app.repository.create_task(
        "SYNTHETIC qualification protocol fixture", kind="validation"
    )["task_id"]
    task = app.repository.create_task("SYNTHETIC frozen definition scope fixture")["task_id"]
    definition = {
        "property_id": "synthetic-DM",
        "definition_version": 1,
        "content_sha256": digest("synthetic-definition"),
    }
    output = {
        "profile_id": "synthetic-unit",
        "version": 1,
        "content_sha256": digest("synthetic-output"),
    }
    spec = {
        "target": {"primary_otype": "Psr"},
        "properties": [{"definition": definition, "output_profile": output}],
    }
    evidence = {"synthetic": True, "checks": ["counterexample A", "held-out B"], "passed": True}
    qualification = {
        "schema_version": "ScientificProfileQualification/1",
        "synthetic": True,
        "owner": "M03",
        "state": "qualified",
        "scientific_profile_validated": True,
        "execution": {
            "model": "qwen3.8-flash",
            "version": "synthetic-1",
            "thinking": False,
            "high_resolution_images": False,
            "operations": ["catalog_header", "catalog_rows"],
            "maximum_input_tokens": 24000,
            "maximum_output_tokens": 8192,
            "maximum_images": 4,
            "maximum_wall_seconds": 60,
            "maximum_inactivity_seconds": 45,
        },
        "scope": {
            "kind": "frozen_properties",
            "source_formats": ["votable"],
            "primary_otypes": ["Psr"],
            "definition_refs": [
                {
                    "id": definition["property_id"],
                    "version": 1,
                    "content_sha256": definition["content_sha256"],
                }
            ],
            "output_profile_refs": [
                {
                    "id": output["profile_id"],
                    "version": 1,
                    "content_sha256": output["content_sha256"],
                }
            ],
        },
    }
    with app.repository.transaction() as conn:
        ev = app.repository.put_object(
            conn, validation, "validation", "synthetic-evidence", 1, evidence
        )
        qualification["validation_evidence_refs"] = [
            {**ev, "task_id": validation, "kind": "validation"}
        ]
        qref = app.repository.put_object(
            conn, validation, "profile_validation", "synthetic-qualification", 1, qualification
        )
        app.repository.put_object(conn, task, "confirmed_query", "synthetic-query", 1, spec)
        app.repository.mutate_task(
            conn,
            task,
            query_ref=canonical(
                {"id": "synthetic-query", "version": 1, "content_sha256": content_hash(spec)}
            ).decode(),
        )
        conn.execute(
            "INSERT INTO settings VALUES(?,?,1)",
            (
                "profile:M03",
                canonical(
                    {
                        "state": "validated",
                        "synthetic": True,
                        "endpoint_identity": digest(
                            app.configuration.runtime["dashscope_base_url"]
                        ),
                        "validation_ref": {**qref, "task_id": validation},
                    }
                ),
            ),
        )
    profile = ModelProfile(
        model="qwen3.8-flash",
        version="synthetic-1",
        state="validated",
        thinking=False,
        operation="catalog_rows",
        source_format="votable",
        wall_seconds=60,
        inactivity_seconds=45,
    )
    return app, task, profile, spec


def multirole_qualification(app, *, ambiguous=False):
    """SYNTHETIC protocol proof only; publishes no real model qualification."""
    with app.repository.transaction() as conn:
        setting = loads(conn.execute("SELECT payload FROM settings WHERE key='profile:M03'").fetchone()[0])
        old = setting['validation_ref']
        report = app.repository.object(conn, old['task_id'], 'profile_validation', old['id'], old['version'])
        template = report.pop('execution')
        report['schema_version'] = 'ScientificProfileQualification/2'
        first = {**template, 'version': 'synthetic-header', 'operations': ['catalog_header'], 'source_formats': ['votable']}
        second = {**template, 'model': 'qwen3.7-plus', 'version': 'synthetic-native',
                  'operations': ['catalog_rows'], 'source_formats': ['votable'], 'maximum_images': 0}
        report['execution_profiles'] = [first, second, dict(second)] if ambiguous else [first, second]
        reference = app.repository.put_object(conn, old['task_id'], 'profile_validation', old['id'], 2, report)
        setting['validation_ref'] = {**reference, 'task_id': old['task_id']}
        conn.execute("UPDATE settings SET payload=? WHERE key='profile:M03'", (canonical(setting),))


def test_distinct_model_roles_have_their_own_version_format_and_capability_bounds(tmp_path):
    app, task, profile, _ = qualified_case(tmp_path)
    multirole_qualification(app)
    header = replace(profile, version='synthetic-header', operation='catalog_header')
    native = replace(profile, version='synthetic-native', model='qwen3.7-plus', max_images=0)
    assert app.profile_authority.authorize(task, 'M03', header, 1000)['model'] == 'qwen3.8-flash'
    assert app.profile_authority.authorize(task, 'M03', native, 1000)['model'] == 'qwen3.7-plus'
    for unsupported in [replace(header, operation='catalog_rows'), replace(native, model='qwen3.8-flash'),
                        replace(native, version='synthetic-header'), replace(native, max_images=1),
                        replace(native, source_format='fits')]:
        with pytest.raises(DomainError):
            app.profile_authority.authorize(task, 'M03', unsupported, 1000)


def test_multiple_matching_execution_grants_cannot_select_the_more_permissive_one(tmp_path):
    app, task, profile, _ = qualified_case(tmp_path)
    multirole_qualification(app, ambiguous=True)
    with pytest.raises(DomainError) as failure:
        app.profile_authority.authorize(task, 'M03', replace(profile,
            version='synthetic-native', model='qwen3.7-plus', max_images=0), 1000)
    assert failure.value.code == 'PROFILE_EXECUTION_AMBIGUOUS'


def test_qualification_is_bound_to_model_operation_input_format_and_frozen_definition(tmp_path):
    app, task, profile, spec = qualified_case(tmp_path)
    assert app.profile_authority.authorize(task, "M03", profile, 1000)["synthetic"] is True
    for changed in [
        replace(profile, model="qwen3.8-max"),
        replace(profile, thinking=True),
        replace(profile, operation="insights"),
        replace(profile, source_format="fits"),
        replace(profile, max_output_tokens=16384),
    ]:
        with pytest.raises(DomainError):
            app.profile_authority.authorize(task, "M03", changed, 1000)
    spec["target"]["primary_otype"] = "G"
    with app.repository.transaction() as conn:
        app.repository.put_object(conn, task, "confirmed_query", "synthetic-query", 2, spec)
        app.repository.mutate_task(
            conn,
            task,
            query_ref=canonical(
                {"id": "synthetic-query", "version": 2, "content_sha256": content_hash(spec)}
            ).decode(),
        )
    with pytest.raises(DomainError) as error:
        app.profile_authority.authorize(task, "M03", profile, 1000)
    assert error.value.code == "PROFILE_TARGET_NOT_VALIDATED"


def test_synthetic_profile_cannot_dispatch_provider_or_reserve_money(tmp_path):
    app, task, profile, _ = qualified_case(tmp_path)
    requests = []
    app.models.transport = httpx.MockTransport(lambda request: requests.append(request))
    with pytest.raises(DomainError) as error:
        asyncio.run(
            app.models.json(
                task_id=task,
                owner="M03",
                root_id="synthetic",
                messages=[{"role": "user", "content": "SYNTHETIC"}],
                profile=profile,
                purpose="production",
            )
        )
    assert error.value.code == "SYNTHETIC_PROFILE_DISPATCH_FORBIDDEN"
    assert requests == [] and app.budget.summary()["committed_micros"] == 0


def test_definition_revision_does_not_inherit_old_qualification(tmp_path):
    app, task, profile, spec = qualified_case(tmp_path)
    spec["properties"][0]["definition"]["definition_version"] = 2
    with app.repository.transaction() as conn:
        app.repository.put_object(conn, task, "confirmed_query", "synthetic-query", 2, spec)
        app.repository.mutate_task(
            conn,
            task,
            query_ref=canonical(
                {"id": "synthetic-query", "version": 2, "content_sha256": content_hash(spec)}
            ).decode(),
        )
    with pytest.raises(DomainError) as error:
        app.profile_authority.authorize(task, "M03", profile, 1000)
    assert error.value.code == "PROFILE_PROPERTY_NOT_VALIDATED"
