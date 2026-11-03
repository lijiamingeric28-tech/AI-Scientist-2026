import pytest

from astroquery_ai.registry.compiler import overlap_witness
from astroquery_ai.registry.service import RegistryService
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.repository import Repository
from tests.rebuild.registry_fixture import make_release


@pytest.fixture
def release(tmp_path):
    package = tmp_path / "synthetic-package"
    make_release(package)
    repo = Repository(tmp_path / "runtime.sqlite3")
    service = RegistryService(tmp_path / "installed-registry", repo, allow_synthetic=True)
    return package, service, repo


def test_synthetic_registry_is_blocked_for_production(release, tmp_path):
    package, service, repo = release
    strict = RegistryService(tmp_path / "production-registry", repo)
    with pytest.raises(DomainError) as error:
        strict.validate(package)
    assert error.value.code == "SYNTHETIC_RELEASE"


def test_import_recompute_vectors_and_idempotence(release):
    package, service, repo = release
    result = service.import_release(package)
    assert result["synthetic"] is True
    assert service.import_release(package)["already_imported"] is True
    loaded = service.load()
    first = service.support(loaded, ["pA*", "*"], "synthetic-subject")
    second = service.support(loaded, ["*", "pA*"], "synthetic-subject")
    assert first == second
    assert len(first["bindings"]) == 1
    assert len(first["bindings"][0]["rule_refs"]) == 2
    assert all(
        rule in first["bindings"][0]["dependency_refs"]
        for rule in first["bindings"][0]["rule_refs"]
    )
    dependencies = {item["id"] for item in first["bindings"][0]["dependency_refs"]}
    assert {
        "synthetic-same-length",
        "synthetic-family",
        "synthetic-subject",
        "synthetic-whole",
        "synthetic-evidence",
        "review-synthetic-length",
    } <= dependencies


def test_bad_hash_and_missing_file_are_errors_not_coverage_gaps(release):
    package, service, repo = release
    (package / "definitions.json").write_text("[]", encoding="utf-8")
    with pytest.raises(DomainError) as error:
        service.validate(package)
    assert error.value.code == "RELEASE_FILE_HASH"
    (package / "definitions.json").unlink()
    with pytest.raises(DomainError) as error:
        service.validate(package)
    assert error.value.code == "CORRUPT_RELEASE"


def test_composition_overlap_finds_three_way_witness_without_runtime_guessing():
    first = {"all_of": [{"otype": "a"}, {"otype": "b"}]}
    second = {"all_of": [{"otype": "b"}, {"otype": "c"}]}
    assert overlap_witness(first, second, [])["otypes"] == ["a", "b", "c"]
    assert overlap_witness(first, second, [{"all_of": [{"otype": "a"}, {"otype": "c"}]}]) is None
