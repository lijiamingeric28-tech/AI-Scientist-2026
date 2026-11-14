import test from 'node:test'
import assert from 'node:assert/strict'
import { runtimeStage } from './runtimeStages.js'

test('sequential extraction describes attachment and source review work', () => {
  const jobs = [{ job_id: 'table', owner: 'M03', kind: 'attachment_extract', status: 'running', payload: { table_id: 'real-table' } },
    { job_id: 'source', owner: 'M06', kind: 'source_reconcile', status: 'ready', payload: { work_id: 'work' } }]
  const stage = runtimeStage({ id: 'extraction' }, { status: 'running', jobs, total: 2, completed: 0 },
    { lifecycle: 'running', execution_stage: { stage_id: 'extraction', running: 1, pending: 1 } })
  assert.match(stage.summary, /1 项正在执行/)
  assert.match(stage.substeps[0].label, /附件/)
  assert.match(stage.substeps[1].label, /作品内/)
})

test('new human review belongs to quality while legacy clean grouping is retained', () => {
  const reviews = [{ review_id: 'review', status: 'pending' }]
  const snapshot = { lifecycle: 'waiting_review', reviews, jobs: [], execution_stage: { stage_id: 'quality' } }
  const quality = runtimeStage({ id: 'quality_check' }, { jobs: [], status: 'waiting' }, snapshot)
  const clean = runtimeStage({ id: 'clean' }, { jobs: [], status: 'waiting' }, snapshot)
  assert.equal(quality.substeps.length, 1)
  assert.equal(quality.substeps[0].status, 'waiting')
  assert.ok(!clean.flows.some(flow => flow.flowId === 'human_review'))
  const legacy = runtimeStage({ id: 'clean' }, { jobs: [], status: 'waiting' }, { reviews, jobs: [] })
  assert.ok(legacy.flows.some(flow => flow.flowId === 'human_review'))
})

test('historical failed catalog work does not hide pending repair or become a waiting-only terminal step', () => {
  const jobs = [{ job_id: 'old', kind: 'catalog_extract', status: 'failed' },
    { job_id: 'repair', kind: 'catalog_extract', status: 'ready' }]
  const project = () => runtimeStage({ id: 'retrieval' }, { jobs }, { execution_stage: { stage_id: 'catalog' } })
  assert.equal(project().groups[0].steps[1].status, 'waiting')
  jobs[1].status = 'succeeded'
  const result = project()
  assert.equal(result.groups[0].steps[1].status, 'error')
  assert.equal(result.errors.length, 1) // The original failed attempt is retained.
})
