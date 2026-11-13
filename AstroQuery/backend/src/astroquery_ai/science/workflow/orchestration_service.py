"""OrchestrationService: ordinary jobs; repository owns state and versions."""

from __future__ import annotations
from astroquery_ai.runtime.codec import loads
from astroquery_ai.runtime.codec import content_hash, digest
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError
from .context import ModuleService


class OrchestrationService(ModuleService):
    handlers = {"start_science": "start", "finalize": "finalize"}

    async def start(self, job):
        tid = job["task_id"]
        # This gate precedes potentially expensive source discovery, too.
        for owner in ("M03", "M06", "M08"):
            pilot = getattr(self.app, 'pilot', None)
            if self.app._profile_state(owner) != "validated" and not (pilot and pilot.authorize_owner(tid, owner)):
                raise DomainError(
                    "PROFILE_NOT_VALIDATED", "科学运行配置尚未通过真实样例校准", owner=owner
                )
        if not self.app.configuration.runtime.get("ads_api_token"):
            raise DomainError("ADS_NOT_CONFIGURED", "尚未配置ADS检索凭据")
        with self.repo.transaction() as conn:
            self.repo.validate_lease(conn, job)
            spec = self.spec(conn, tid)
            from ..reader_profiles import pin_reader_profile
            pin_reader_profile(self.app, conn, tid, spec)
            for producer in (
                "catalog_hints",
                "catalog_discovery",
                "literature_candidates",
                "selections",
                "body_batches",
                "attachment_discovery",
                "catalog_measurements",
                "paper_measurements",
            ):
                self.repo.producer(conn, tid, producer)
            catalog = self.repo.enqueue(
                conn, tid, "M03", "catalog_discover", {"spec_ref": job["payload"]["spec_ref"]}
            )
            self.repo.enqueue(
                conn,
                tid,
                "M04",
                "literature_discover",
                {"spec_ref": job["payload"]["spec_ref"]},
                dependencies=[catalog],
            )
            from astroquery_ai.runtime.stages import EXECUTION_POLICY, set_stage
            self.repo.put_object(conn, tid, 'execution_policy', tid, 1, EXECUTION_POLICY)
            set_stage(self.repo, conn, tid, 'catalog')
            self.repo.finish_job(conn, job)

    async def finalize(self, job):
        with self.repo.transaction() as conn:
            # Seal itself validates closure and returns the immutable delivery
            # on replay. A duplicate completion job cannot reopen the science.
            self.repo.validate_lease(conn, job, scientific=False)
            task = self.repo.task(conn, job['task_id'])
            if task['science_state'] != 'sealed':
                self.repo.guard_definitions(conn, task)
            coverage = self.repo.objects(conn, job["task_id"], "coverage")
            outcome = (
                "partial"
                if any(
                    c.get("state") in {"partial", "failed", "truncated_or_unknown", "unreadable"}
                    for c in coverage
                )
                else "completed"
            )
            delivery=self.app.delivery.seal(conn, job["task_id"], outcome=outcome)
            # This synchronous operation has held the same BEGIN IMMEDIATE
            # write transaction since validating the lease above, with no
            # await or opportunity for another owner to reclaim it. Account
            # for local serialization time before the normal commit check;
            # still require the exact running token/generation. Never do this
            # across network waits or a released transaction.
            import time
            conn.execute(
                "UPDATE jobs SET lease_until=max(lease_until,?) "
                "WHERE job_id=? AND status='running' AND lease_token=? AND generation=?",
                (time.time()+60, job['job_id'], job['lease_token'], job['generation']),
            )
            self.repo.finish_job(conn, job)
            from astroquery_ai.runtime.run_policy import consolidated
            from ..author_release import enabled as author_enabled
            if consolidated(self.spec(conn,job['task_id'])) and not author_enabled(self.spec(conn,job['task_id'])):
                self.repo.mutate_task(conn,job['task_id'],insight_ref=canonical(delivery['insight']['report_ref']).decode(),
                    lifecycle='completed',phase='insight')
                from astroquery_ai.runtime.stages import set_stage
                set_stage(self.repo,conn,job['task_id'],'insight')
                self.repo.event(conn,job['task_id'],'insight_updated',{'report_ref':delivery['insight']['report_ref'],
                    'status':'disabled_pending_content','model_calls':0})
                self.repo.event(conn,job['task_id'],'task_state_changed',{'lifecycle':'completed'})
                return
            self.repo.enqueue(
                conn,
                job["task_id"],
                "M11",
                "insights",
                {"delivery_id": loads(self.repo.task(conn, job["task_id"])["delivery_ref"])["id"]},
            )
            from astroquery_ai.runtime.stages import current_stage, set_stage
            if current_stage(conn, job['task_id']):
                set_stage(self.repo, conn, job['task_id'], 'insight')

    async def advance(self, tid):
        with self.repo.transaction() as conn:
            task = self.repo.task(conn, tid)
            if (
                not task["query_ref"]
                or task["science_state"] != "open"
                or task["lifecycle"] not in {"running", "queued"}
            ):
                return
            spec = self.spec(conn, tid)
            if spec.get('run_policy', {}).get('quality', {}).get('official_table_review') == 'shared_semantics/1':
                from astroquery_ai.runtime.stages import advance_stage, current_stage
                checkpoint = current_stage(conn, tid)
                kind = {'quality': 'assess_batch', 'normalization': 'normalize'}.get((checkpoint or {}).get('stage_id'))
                if kind and conn.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind=? AND status IN ('ready','running') LIMIT 1",
                                         (tid, kind)).fetchone():
                    # A local row consumer can create more jobs, but it does
                    # not change source coverage or release a final delivery.
                    advance_stage(self.repo, conn, tid)
                    return
            # A material-only experiment uses the same preparation/acquisition
            # jobs, but must never reach quality, publication or insight. This
            # guard also covers the automatic advance following the last job.
            from ..literature_preparation import materials_only, schedule
            if materials_only(spec):
                schedule(self.repo, conn, tid)
                preparations = self.repo.objects(conn, tid, 'material_preparation')
                if preparations and preparations[0]['closed']:
                    allowed = {'literature_discover', 'material_prepare', 'acquire_work', 'reconcile'}
                    unexpected = [dict(r) for r in conn.execute(
                        'SELECT kind,status FROM jobs WHERE task_id=?', (tid,)) if r['kind'] not in allowed]
                    if unexpected:
                        raise DomainError('MATERIAL_BOUNDARY_BREACH', '材料实验出现范围外作业', jobs=unexpected)
                    self.repo.mutate_task(conn, tid, lifecycle='paused', resume_required=0,
                                          terminal_reason='material_experiment_frozen')
                    self.repo.event(conn, tid, 'material_experiment_frozen',
                                    {'downstream_scheduled':False, 'science_delivery_created':False})
                else:
                    from astroquery_ai.runtime.stages import advance_stage
                    advance_stage(self.repo, conn, tid)
                return
            # A source-level check follows its actual reading, before publication.
            from astroquery_ai.science.catalog.selection import replenish
            replenish(self.repo, conn, tid)
            from astroquery_ai.science.literature_preparation import schedule
            schedule(self.repo,conn,tid)
            from astroquery_ai.runtime.extraction_experiment import enabled, advance_extraction
            if enabled(spec):
                advance_extraction(self, conn, tid, spec)
                return
            # Repeated mentions and newly available context are scientific work,
            # not separate measurements just because they arose in another batch.
            planned = {p['source_id']: p for p in self.repo.objects(conn, tid, 'source_review_plan')}
            bounded_reading = spec.get('run_policy', {}).get('reading', {}).get('review') == 'work_property_once'
            from astroquery_ai.runtime.run_policy import consolidated
            unified=consolidated(spec)
            if unified:
                from ..unified_quality import advance_quality
                advance_quality(self,conn,tid,spec)
            measurements = self.repo.objects(conn, tid, 'measurement')
            candidates = self.repo.objects(conn, tid, 'candidate')
            review_rows = [(row['status'], loads(row['payload'])) for row in conn.execute('SELECT status,payload FROM reviews WHERE task_id=?', (tid,))]
            withdrawals = self.repo.objects(conn, tid, 'review_withdrawal')
            withdrawn_questions = {w['review_id'] for w in withdrawals}
            recovered = {r['candidate_id'] for r in self.repo.objects(conn, tid, 'source_review_recovery')}
            for row in conn.execute("SELECT payload FROM jobs WHERE task_id=? AND kind='source_reconcile' AND status IN ('ready','running','waiting_dependency')", (tid,)):
                payload = loads(row[0])
                if payload.get('recovery_from_withdrawal_ref'):
                    recovered.update(ref['id'] for ref in payload['items'] if ref['kind'] == 'candidate')
            human_candidates = {cid for status, question in review_rows
                if not (status == 'closed_unanswered' and question['review_id'] in withdrawn_questions)
                for cid in question['scope'].get('candidate_ids', [])}
            records_by_id = {m['measurement_id']: m for m in measurements}
            candidates_by_id = {c['candidate_id']: c for c in candidates}
            awaiting_sources = set()
            for state, question in review_rows:
                if state not in {'pending', 'accepted'}:
                    continue
                awaiting_sources.update(records_by_id[mid]['source_ref']['id']
                    for mid in question['scope'].get('measurement_ids', []) if mid in records_by_id)
                for cid in question['scope'].get('candidate_ids', []):
                    candidate = candidates_by_id.get(cid, {})
                    sid = candidate.get('assembly_context', {}).get('source', {}).get('source_id')
                    if sid:
                        awaiting_sources.add(sid)
            for source in ([] if unified else self.repo.objects(conn, tid, 'source')):
                sid = source['source_id']
                if source['kind'] != 'paper' or sid in awaiting_sources:
                    continue
                batches = conn.execute("SELECT status FROM jobs WHERE task_id=? AND kind='paper_batch' AND json_extract(CAST(payload AS TEXT),'$.work_id')=?", (tid, sid)).fetchall()
                if not batches or any(row[0] not in {'succeeded', 'failed', 'not_run', 'cancelled'} for row in batches):
                    continue
                items = [{'kind': 'measurement', 'id': m['measurement_id'], 'version': m['revision'], 'content_sha256': m['content_sha256']}
                         for m in measurements if m['source_ref']['id'] == sid]
                for candidate in candidates:
                    if (candidate['state'] == 'review_candidate' and candidate['candidate_id'] not in human_candidates
                            and candidate['candidate_id'] not in recovered
                            and candidate.get('assembly_context', {}).get('source', {}).get('source_id') == sid):
                        items.append({'kind': 'candidate', 'id': candidate['candidate_id'], 'version': 1, 'content_sha256': content_hash(candidate)})
                items.sort(key=lambda item: (item['kind'], item['id']))
                if bounded_reading:
                    if not any(p.get('source_id') == sid for p in self.repo.objects(conn,tid,'figure_reuse_plan')):
                        self.repo.put_object(conn,tid,'figure_reuse_plan',sid,1,{'source_id':sid,'reading_complete':True})
                        self.repo.enqueue(conn,tid,'M06','paper_figures',{'work_id':sid,
                            'artifact_ref':source['artifact']['artifact_id'],'reuse_body_hints':True})
                    # Frozen once per actual work/property input; admitting a
                    # candidate must not create a new review of its own result.
                    for pid in source['work']['allowed_property_ids']:
                        scope_id = 'source-property-' + digest([sid,pid])
                        if any(p.get('scope_id') == scope_id for p in self.repo.objects(conn,tid,'source_review_plan')):
                            continue
                        own = [item for item in items if item['kind'] == 'candidate'
                               and candidates_by_id[item['id']]['proposal']['property_id'] == pid]
                        self.repo.put_object(conn,tid,'source_review_plan',scope_id,1,
                            {'scope_id':scope_id,'source_id':sid,'property_id':pid,'items':own,'revision':1})
                        from ..source_review import initial_review_groups
                        index = self.repo.object(conn,tid,'document_index',sid)
                        pages = {p['page']:p['text'] for p in index['pages']}
                        from ..prompt_contracts import property_view
                        from astroquery_ai.runtime.codec import canonical
                        binding=next(b for b in self.spec(conn,tid)['properties'] if b['property_id']==pid)
                        context_pages={r['request']['page'] for r in self.repo.objects(conn,tid,'reading_context_request')
                            if r['work_id']==sid and r['property_id']==pid and r['request'].get('page') in pages}
                        context_blocks=[b for n in self.repo.objects(conn,tid,'reading_context_note')
                                        if n['work_id']==sid and n['property_id']==pid for b in n['blocks']]
                        for group in initial_review_groups(own,candidates_by_id,pages,target=self.spec(conn,tid)['target'],
                                property_bytes=len(canonical(property_view(binding))),context_pages=context_pages,context_blocks=context_blocks):
                            self.repo.enqueue(conn,tid,'M06','source_reconcile',{'work_id':sid,
                                'property_id':pid,'items':group, 'consolidated_review':True})
                    continue
                control_basis = digest([w['withdrawal_id'] for w in withdrawals if w['source_id'] == sid])
                if (sid in planned and sorted(planned[sid]['items'], key=lambda item: (item['kind'], item['id'])) == items
                        and planned[sid].get('control_basis_hash', digest([])) == control_basis):
                    continue
                prior_version = conn.execute("SELECT coalesce(max(version),0) FROM objects WHERE task_id=? AND kind='source_review_plan' AND object_id=?", (tid, sid)).fetchone()[0]
                plan_version = prior_version + 1
                self.repo.put_object(conn, tid, 'source_review_plan', sid, plan_version, {'source_id': sid, 'items': items, 'revision': plan_version, 'one_plan_per_actual_input': True, 'control_basis_hash': control_basis})
                for start in range(0, len(items), 24):
                    self.repo.enqueue(conn, tid, 'M06', 'source_reconcile', {'work_id': sid, 'items': items[start:start + 24], 'source_plan_revision': plan_version})
            # Transport/format failures remain explicit owner-module gaps, not
            # scientific questions for the user. Actual unresolved assessments
            # are handled by apply_source_recheck after a completed check.
            jobs = [
                dict(row)
                for row in conn.execute("SELECT kind,status FROM jobs WHERE task_id=?", (tid,))
            ]
            if unified:
                # Comparison is a pre-seal job after the whole quality/cleaning
                # batch. Its localized repairs reopen only those quality jobs.
                terminal={'succeeded','failed','not_run','cancelled'}
                before={'paper_batch','attachment_extract','paper_figures','paper_figure_page','quality_verify',
                    'quality_reextract','quality_citation_enrich','assess_batch','apply_review','normalize','interpret_uncertainty'}
                pending_review=conn.execute("select 1 from reviews where task_id=? and status in ('pending','accepted')",(tid,)).fetchone()
                preparation=self.repo.objects(conn,tid,'material_preparation')
                if (not preparation or preparation[0]['closed']) and not pending_review and not any(
                        j['kind'] in before and j['status'] not in terminal for j in jobs):
                    from ..archive_comparison import schedule as schedule_comparison
                    schedule_comparison(self,conn,tid,self.spec(conn,tid))
                    jobs=[dict(r) for r in conn.execute('select kind,status from jobs where task_id=?',(tid,))]
            if bounded_reading and not any(j['kind'] in {'paper_batch','source_reconcile'} and
                    j['status'] not in {'succeeded','failed','not_run','cancelled'} for j in jobs):
                planned_citations = {p['source_id'] for p in self.repo.objects(conn,tid,'citation_enrichment_plan')}
                source_ids = {r['source_ref']['id'] for r in self.repo.objects(conn,tid,'reported_source_ref')}
                for sid in sorted(source_ids - planned_citations):
                    self.repo.put_object(conn,tid,'citation_enrichment_plan',sid,1,{'source_id':sid,'depth':1,'abstract_only':True})
                    self.repo.enqueue(conn,tid,'M06','citation_enrich',{'work_id':sid})
                jobs = [dict(r) for r in conn.execute('SELECT kind,status FROM jobs WHERE task_id=?',(tid,))]
            # Close producers only after all authorized children of that scope end.
            producer_scopes = [
                (
                    "catalog_measurements",
                    {
                        "catalog_discover",
                        "catalog_extract",
                        "literature_discover",
                        "acquire_window", "acquire_work",
                        "attachment_discover",
                        "attachment_extract",
                    },
                ),
                (
                    "attachment_discovery",
                    {"literature_discover", "acquire_window", "acquire_work", "attachment_discover"},
                ),
                ("body_batches", {"literature_discover", "acquire_window", "acquire_work", "paper_batch", "source_reconcile", 'citation_enrich'}),
                ("paper_measurements", {"literature_discover", "acquire_window", "acquire_work", "paper_batch", "source_reconcile", "apply_source_recheck"}),
                ("reading_recovery", {"paper_batch", "source_reconcile", "apply_source_recheck"}),
            ]
            producer_scopes.extend((row[0], {'paper_batch', 'source_reconcile', 'apply_source_recheck'})
                                   for row in conn.execute("SELECT producer_id FROM producers WHERE task_id=? AND producer_id LIKE 'reading_recovery_%'", (tid,)))
            for producer, kinds in producer_scopes:
                preparations=self.repo.objects(conn,tid,'material_preparation')
                if preparations and not preparations[0]['closed']:
                    continue  # No preparation gap may close a future producer.
                if producer in {'catalog_measurements','attachment_discovery','body_batches','paper_measurements'}:
                    kinds={*kinds,'material_prepare'}
                if all(
                    j["status"] in {"succeeded", "failed", "not_run", "cancelled"}
                    for j in jobs
                    if j["kind"] in kinds
                ) and any(j["kind"] in kinds for j in jobs):
                    state = conn.execute(
                        "SELECT state,watermark FROM producers WHERE task_id=? AND producer_id=?",
                        (tid, producer),
                    ).fetchone()
                    if state and state["state"] == "open":
                        self.repo.producer(
                            conn,
                            tid,
                            producer,
                            close_reason="authorized_jobs_closed",
                            watermark=state["watermark"],
                        )
            from astroquery_ai.runtime.stages import advance_stage, current_stage, JOB_STAGE
            advance_stage(self.repo, conn, tid)
            checkpoint = current_stage(conn, tid)
            active = any(
                j["status"] in {"ready", "running", "waiting_dependency", "awaiting_review"}
                and (not checkpoint or JOB_STAGE.get(j['kind']) in {None, checkpoint['stage_id']})
                for j in jobs
            )
            reviews = conn.execute(
                "SELECT 1 FROM reviews WHERE task_id=? AND status IN ('pending','accepted') LIMIT 1",
                (tid,),
            ).fetchone()
            if not active and reviews:
                self.repo.mutate_task(conn, tid, lifecycle="waiting_review", phase="quality")
                self.repo.event(conn, tid, "task_state_changed", {"lifecycle": "waiting_review"})
            elif not active and not reviews and not conn.execute(
                "SELECT 1 FROM producers WHERE task_id=? AND state<>'closed' LIMIT 1", (tid,)
            ).fetchone():
                self.repo.enqueue(
                    conn, tid, "M13", "finalize", {"spec_ref": loads(task["query_ref"])}
                )
            advance_stage(self.repo, conn, tid)
