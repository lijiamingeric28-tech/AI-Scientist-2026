from astroquery_ai.runtime.paths import knowledge_content_root
"""Real content adapter with explicitly synthetic scientific bindings only."""
from pathlib import Path

import pytest

from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.bound_knowledge import package_content
from tests.rebuild.scenario import application

CONTENT = knowledge_content_root()


def package(app, path, *, claim='radio.dispersion.c1', condition_mode=None):
    registry = app.registry.load()
    registry_ref = {'id': registry['manifest']['release_id'], 'version': 1,
                    'content_sha256': registry['manifest']['content_sha256']}
    entry_id = claim.rsplit('.', 1)[0]
    entry = next(e for e in loads((CONTENT / 'content/entries.json').read_bytes()) if e['entry_id'] == entry_id)
    definition = registry['data']['definitions'][0]
    binding = {'binding_id': 'SYNTHETIC content binding', 'registry_release_ref': registry_ref,
        'entry_ref': {'id': entry_id, 'version': entry['revision'], 'content_sha256': entry['content_hash']},
        'claim_ids': [claim], 'subject_class_ids': ['synthetic-subject'], 'object_scale': 'synthetic-whole',
        'otype_scope': [entry['otype_scope'][0]], 'property_bindings': [{'property_id': definition['property_id'],
            'definition_version': definition['definition_version'], 'definition_hash': definition['content_sha256']}],
        'required_conditions': [], 'excluded_conditions': []}
    if condition_mode:
        binding['content_condition_bindings'] = [{'condition_id': c['condition_id'], 'mode': condition_mode,
            'explanation': 'SYNTHETIC explicit mapping: tests selection only, no scientific applicability claim.'} for c in entry.get('conditions', [])]
    review = {'review_id': 'SYNTHETIC binding review', 'review_version': 1,
        'decision': 'approved', 'reviewer_kind': 'synthetic_fixture', 'unresolved': [],
        'reviewed_payload_sha256': digest(binding)}
    review['content_sha256'] = content_hash(review)
    binding['review_ref'] = {'id': review['review_id'], 'version': 1, 'content_sha256': review['content_sha256']}
    package_content(CONTENT, path, release_id='SYNTHETIC content runtime', registry_ref=registry_ref,
        bindings=[binding], reviews=[review], synthetic=True)
    query = {'registry_release': registry_ref,
        'target': {'classification_assertions': [], 'primary_otype': entry['otype_scope'][0]},
        'properties': [{'property_id': definition['property_id'], 'definition': definition,
                        'output_profile': {'object_scale_id': 'synthetic-whole'}}]}
    return query


@pytest.mark.parametrize('mode,scope', [('frozen_definition', 'applicable_background'), ('conditional_background', 'conditional_background')])
def test_explicit_condition_binding_differs_from_unresolved_background_and_wrong_versions(tmp_path, mode, scope):
    app = application(tmp_path / 'data')
    query = package(app, tmp_path / 'bound', condition_mode=mode)
    app.knowledge.import_release(tmp_path / 'bound')
    release = app.knowledge.load()
    choices = app.knowledge.select(release, query, [])
    assert choices and choices[0]['scope'] == scope
    assert choices[0]['claim']['authoring_basis'] == 'author_knowledge'
    assert choices[0]['author_review']['independent_human_review'] is False
    query['properties'][0]['definition']['content_sha256'] = digest('SYNTHETIC other definition version')
    assert app.knowledge.select(release, query, []) == []


@pytest.mark.parametrize('claim,basis,source_count', [('radio.dispersion.c1', 'author_knowledge', 0),
    ('taxonomy.codes.verified1', 'source_verified', 1)])
def test_import_preserves_real_author_basis_and_never_establishes_unknown_conditions(tmp_path, claim, basis, source_count):
    app = application(tmp_path / 'data')
    query = package(app, tmp_path / 'bound', claim=claim)
    app.knowledge.import_release(tmp_path / 'bound')
    release = app.knowledge.load()
    choices = app.knowledge.select(release, query, [])
    assert len(choices) == 1
    choice = choices[0]
    assert choice['claim']['authoring_basis'] == basis
    assert len(choice['sources']) == source_count
    assert choice['scope'] == 'conditional_background'
    assert choice['conditions_zh'] and choice['limitations'] and choice['uncertainty_notes']
    assert choice['author_review']['independent_human_review'] is False
    assert release['data']['origin:content/reviews.json'][0]['decision'] == 'author_checked'
    assert app.budget.summary()['committed_micros'] == 0
    # The content manifest remains explicitly unbound; only this synthetic
    # wrapper has a registry binding. Never modify/activate the real package.
    assert loads((CONTENT / 'content-manifest.json').read_bytes())['activation_allowed'] is False


@pytest.mark.parametrize('mutation', ['claim_basis', 'definition'])
def test_rehashed_wrapper_cannot_rewrite_claim_basis_or_attach_unreviewed_definition(tmp_path, mutation):
    import hashlib
    app = application(tmp_path / 'data')
    root = tmp_path / 'bound'
    package(app, root)
    manifest = loads((root / 'manifest.json').read_bytes())
    role = 'entries' if mutation == 'claim_basis' else 'bindings'
    data = loads((root / (role + '.json')).read_bytes())
    if mutation == 'claim_basis':
        data[0]['claims'][0]['authoring_basis'] = 'source_verified'
    else:
        data[0]['property_bindings'][0]['definition_hash'] = digest('SYNTHETIC changed definition')
    raw = canonical(data)
    (root / (role + '.json')).write_bytes(raw)
    next(x for x in manifest['content_files'] if x['role'] == role)['sha256'] = hashlib.sha256(raw).hexdigest()
    manifest['content_sha256'] = content_hash(manifest)
    (root / 'manifest.json').write_bytes(canonical(manifest))
    with pytest.raises(DomainError) as error:
        app.knowledge.validate(root)
    assert error.value.code == ('KB_CONTENT_REWRITTEN' if mutation == 'claim_basis' else 'KB_REVIEW_STALE')


def test_original_unbound_content_cannot_be_imported_as_runtime_knowledge(tmp_path):
    app = application(tmp_path / 'data')
    with pytest.raises(DomainError):
        app.knowledge.import_release(CONTENT)
    with pytest.raises(DomainError, match='缺少正式性质绑定'):
        package_content(CONTENT, tmp_path / 'absent', release_id='SYNTHETIC missing', registry_ref={}, bindings=[], reviews=[])
    assert not (tmp_path / 'absent').exists()
