from astroquery_ai.runtime.repository import Repository
from astroquery_ai.science.identity_query import cached_identity_response


def test_column_partitions_reuse_first_successful_raw_response_only_in_same_task(tmp_path):
    repo = Repository(tmp_path / 'SYNTHETIC cache.sqlite3')
    tid = repo.create_task('SYNTHETIC frozen query')['task_id']
    other = repo.create_task('SYNTHETIC different query')['task_id']
    query = {'query_column': 'Name', 'selector': 'SYNTHETIC target', 'datatype': 'char'}
    raw = {'table_id': 'SYNTHETIC/v1/table', 'query_execution': query,
           'response_artifact': {'artifact_id': 'SYNTHETIC first raw'}, 'response_metadata': {'status': 200}}
    with repo.transaction() as c:
        repo.put_object(c, other, 'catalog_identity_query', 'SYNTHETIC other task', 1, raw)
        repo.put_object(c, tid, 'catalog_identity_query', 'SYNTHETIC failed', 1,
                        {**raw, 'response_artifact': None, 'response_metadata': {'status': 503}})
        assert cached_identity_response(repo, c, tid, raw['table_id'], query) is None
        first = repo.put_object(c, tid, 'catalog_identity_query', 'SYNTHETIC actual query', 1, raw)
        repo.put_object(c, tid, 'catalog_identity_query', 'SYNTHETIC actual query', 2,
                        {**raw, 'state': 'verified_target_rows'})
        repo.put_object(c, tid, 'catalog_identity_query', 'SYNTHETIC later response', 1,
                        {**raw, 'response_artifact': {'artifact_id': 'SYNTHETIC later raw'}})
        hit = cached_identity_response(repo, c, tid, raw['table_id'], query)
        assert hit['response_artifact'] == raw['response_artifact']
        assert hit['cache_record_ref'] == first
        assert cached_identity_response(repo, c, tid, raw['table_id'], {**query, 'selector': 'SYNTHETIC different'}) is None
        assert cached_identity_response(repo, c, tid, 'SYNTHETIC/v2/table', query) is None
        assert cached_identity_response(repo, c, tid, raw['table_id'], {**query, 'datatype': 'long'}) is None
