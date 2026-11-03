from copy import deepcopy
import pytest

from astroquery_ai.runtime.codec import content_hash
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.delivery import current_delivery_measurements
from astroquery_ai.science.quality import check_native_dimension
from tests.rebuild.factories import measurement, error_component


@pytest.mark.parametrize('native,target,reject', [('Hz', 's', True), ('m/s', 'm', True),
                                                ('cm', 'm', False), ('deg_C', 'K', False),
                                                ('1', 'deg', False), (None, 'm', False),
                                                ('SYNTHETIC_UNKNOWN', 'm', False), ('mag', 'mJy', False)])
def test_only_explicit_wrong_linear_dimension_is_quarantined_with_raw_retained(tmp_path, native, target, reject):
    repo = Repository(tmp_path / 'SYNTHETIC quantity.sqlite3')
    tid = repo.create_task('SYNTHETIC native dimension')['task_id']
    record = measurement(components=[error_component('SYNTHETIC independent error')])
    record.update(source_kind='catalog', unit=native)
    binding = {'output_profile': {'unit': {'kind': 'physical', 'canonical_symbol': target},
                                  'representation': {'kind': 'linear'}}}
    with repo.transaction() as c:
        source = {'source_id': 'SYNTHETIC table', 'kind': 'catalog', 'metadata': {'columns': [
            {'name': 'reported_value', 'datatype': 'double', 'unit_text': native}]}}
        record['source_ref'] = repo.put_object(c, tid, 'source', source['source_id'], 1, source)
        record['interpretation_ref'] = repo.put_object(c, tid, 'interpretation', 'SYNTHETIC interpretation', 1,
            {'producer': 'M03', 'proposal': {'column': 'reported_value'}})
        record['content_sha256'] = content_hash(record)
        repo.put_object(c, tid, 'measurement', record['measurement_id'], 1, record)
        before = deepcopy(record)
        assert check_native_dimension(repo, c, tid, record, binding) is not reject
        assert record == before
        dispositions = repo.objects(c, tid, 'admission_disposition')
        assert current_delivery_measurements([record], dispositions) == ([] if reject else [record])
        if reject:
            assert dispositions[0]['owner'] == 'M07'
            assert dispositions[0]['scientific_derivation_performed'] is False
            assert repo.object(c, tid, 'measurement', record['measurement_id']) == before
            assert not check_native_dimension(repo, c, tid, record, binding)
            assert len(repo.objects(c, tid, 'admission_disposition')) == 1
        assert c.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
