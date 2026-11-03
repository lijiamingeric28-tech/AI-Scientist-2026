from uuid import uuid4
import pytest
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.reviews import ReviewService, ReviewAnswer
from astroquery_ai.runtime.errors import DomainError


def test_api_simulation_needs_registered_task_and_does_not_create_a_question(tmp_path):
    repo=Repository(tmp_path/'simulation.sqlite3');tid=repo.create_task('SYNTHETIC ordinary acceptance')['task_id']
    with repo.transaction() as c:repo.mutate_task(c,tid,lifecycle='running',science_state='open')
    answer=ReviewAnswer(task_id=tid,review_id=str(uuid4()),review_revision=1,basis_hash='0'*64,
        client_request_id=str(uuid4()),action='unable',reason='SYNTHETIC test',simulation=True)
    service=ReviewService(repo)
    with pytest.raises(DomainError) as e:service.answer(answer)
    assert e.value.code=='REVIEW_SIMULATION_SCOPE'
    with repo.transaction() as c:repo.put_object(c,tid,'query_acceptance_run',tid,1,
        {'schema_version':'NormalQueryAcceptance/1','task_id':tid,'simulation_authorized':True})
    with pytest.raises(DomainError) as e:service.answer(answer)
    assert e.value.code=='REVIEW_NOT_FOUND'
