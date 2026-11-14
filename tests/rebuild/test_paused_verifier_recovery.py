from uuid import uuid4
import pytest

from astroquery_ai.runtime.codec import canonical, digest
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.reviews import ReviewService


@pytest.mark.parametrize('mode', ['pause_before_dispatch', 'real_semantic_doubt', 'actual_verifier', 'answered'])
def test_resume_only_withdraws_unanswered_pause_control_question(tmp_path, mode):
    repo = Repository(tmp_path / 'SYNTHETIC paused-check.sqlite3')
    tid = repo.create_task('SYNTHETIC paused verifier')['task_id']
    with repo.transaction() as c:
        spec = {'spec_hash': digest('SYNTHETIC frozen request')}
        qr = repo.put_object(c, tid, 'confirmed_query', 'SYNTHETIC spec', 1, spec)
        repo.mutate_task(c, tid, lifecycle='running', science_state='open', query_ref=canonical(qr).decode())
        check = {'attempt_id': 'SYNTHETIC actual verifier' if mode == 'actual_verifier' else None,
                 'check': None, 'failure': 'DISPATCH_FORBIDDEN' if mode != 'real_semantic_doubt' else 'source_semantics_unresolved'}
        evidence = {'evidence_id': 'SYNTHETIC evidence', 'raw_text': 'SYNTHETIC original value and header'}
        er = repo.put_object(c, tid, 'evidence', evidence['evidence_id'], 1, evidence)
        candidate = {'candidate_id': 'SYNTHETIC candidate', 'state': 'review_candidate',
            'reason': 'local_subject_or_result_evidence_unresolved',
            'assembly_context': {'owner': 'M06', 'source': {'source_id': 'SYNTHETIC source'},
                                 'paper_verification': check}}
        cr = repo.put_object(c, tid, 'candidate', candidate['candidate_id'], 1, candidate)
        question = ReviewService(repo).register(c, tid, {
            'origin': 'M06', 'owner': 'M06', 'issue_kind': 'quantity_semantics',
            'issue_key': 'SYNTHETIC check', 'scope': {'candidate_ids': [candidate['candidate_id']]},
            'question': 'SYNTHETIC question', 'impact': 'SYNTHETIC admission',
            'basis': {'candidate_ref': cr, 'spec_hash': spec['spec_hash']}, 'evidence_refs': [er]})
        if mode == 'answered':
            c.execute("UPDATE reviews SET status='accepted',answer=? WHERE review_id=?",
                      (canonical({'SYNTHETIC prior human answer': True}), question['review_id']))
    before = repo.get_task(tid)
    paused = repo.control(tid, 'pause', str(uuid4()), before['revision'])
    resumed = repo.control(tid, 'continue', str(uuid4()), paused['revision'])
    assert resumed['lifecycle'] == 'queued'
    with repo.read() as c:
        row = c.execute('SELECT * FROM reviews WHERE review_id=?', (question['review_id'],)).fetchone()
        withdrawals = repo.objects(c, tid, 'review_withdrawal')
        if mode == 'pause_before_dispatch':
            assert row['status'] == 'closed_unanswered' and row['answer'] is None
            assert len(withdrawals) == 1 and withdrawals[0]['scientific_decision_made'] is False
            assert withdrawals[0]['candidate_ref'] == cr
            assert repo.object(c, tid, 'candidate', candidate['candidate_id']) == candidate
        else:
            assert row['status'] == ('accepted' if mode == 'answered' else 'pending')
            assert not withdrawals
        assert c.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
