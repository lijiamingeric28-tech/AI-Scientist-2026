"""InsightService: ordinary jobs; repository owns state and versions."""

from __future__ import annotations
import asyncio
from astroquery_ai.runtime.codec import canonical, loads
from astroquery_ai.runtime.errors import DomainError
from .context import ModuleService
from ..insight_inputs import build_units, explanation_prompt, measurement_input


class InsightService(ModuleService):
    handlers = {"insights": "insights"}

    async def insights(self, job):
        tid = job["task_id"]
        with self.repo.read() as conn:
            task=self.repo.task(conn,tid)
            ref=loads(task['query_ref'])
            frozen=self.repo.object(conn,tid,'confirmed_query',ref['id'],ref['version'])
        from ..author_release import enabled
        if enabled(frozen):
            from ..property_insights import enabled as property_enabled
            if property_enabled(frozen):
                from ..property_insight_generation import generate
                return await generate(self,job)
            from ..author_insights import generate
            return await generate(self,job)
        with self.repo.read() as conn:
            delivery = self.app.delivery.get(conn, tid, job["payload"]["delivery_id"])
            # Delivered science is immutable even if a later registry revocation
            # prevents further scientific calls. Facts remain readable.
            task = self.repo.task(conn, tid)
            spec = self.repo.object(conn, tid, "confirmed_query", loads(task["query_ref"])["id"])
            from astroquery_ai.runtime.science_capabilities import verification_scope
            verification = verification_scope(self.repo, conn, tid, spec)
            selection_only = verification is not None and verification.get("insight_selection_only") is True
        if spec.get('run_policy',{}).get('insights',{}).get('mode')=='disabled_pending_content':
            from ..author_knowledge import disabled_report
            report=disabled_report(delivery)
            with self.repo.transaction() as conn:
                self.repo.validate_lease(conn,job,scientific=False)
                reference=self.repo.put_object(conn,tid,'insight',report['report_id'],1,report)
                self.repo.finish_job(conn,job)
                self.repo.mutate_task(conn,tid,insight_ref=canonical(reference).decode(),lifecycle='completed',phase='insight')
                self.repo.event(conn,tid,'insight_updated',{'report_ref':reference,'status':'disabled_pending_content','model_calls':0})
            return
        knowledge, choices, reason, pins = None, [], None, []
        try:
            with self.repo.read() as conn:
                pins = self.repo.objects(conn, tid, "insight_knowledge_pin")
            if pins:
                if pins[0]["reference"] is None:
                    raise DomainError("KB_UNAVAILABLE", "首次洞察调度时没有可用知识库")
                knowledge = self.app.knowledge.load(pins[0]["reference"])
            else:
                knowledge = self.app.knowledge.load()
            from ..context_views import delivery_contexts
            choices = self.app.knowledge.select(knowledge, spec, delivery_contexts(delivery))
            if not choices:
                reason = "no_applicable_knowledge"
        except DomainError:
            reason = "kb_unavailable"
        if not pins:
            with self.repo.transaction() as conn:
                self.repo.validate_lease(conn, job, scientific=False)
                self.repo.put_object(
                    conn,
                    tid,
                    "insight_knowledge_pin",
                    delivery["delivery_id"],
                    1,
                    {
                        "reference": {
                            "id": knowledge["manifest"]["release_id"],
                            "version": 1,
                            "content_sha256": knowledge["manifest"]["content_sha256"],
                        }
                        if knowledge
                        else None,
                        "delivery_id": delivery["delivery_id"],
                        "reason": reason,
                    },
                )
        units = build_units(delivery, spec, choices, reason)
        if selection_only:
            reason = "stage1_knowledge_selection_only"
        from astroquery_ai.runtime.calls import input_upper_bound

        if not selection_only and units and self.app._profile_state("M11") == "validated":
            async def explain_one(offset):
                selected_units = units[offset : offset + 1]
                from ..insight_inputs import explanation_bindings,explanation_wire
                wire_binding=explanation_bindings(selected_units,delivery)
                prompt = explanation_wire(explanation_prompt(selected_units, delivery, spec),wire_binding)
                messages = [{"role": "user", "content": canonical(prompt).decode()}]
                if input_upper_bound(messages) > 16000:
                    for unit in selected_units:
                        unit["reason"] = "complete_unit_exceeds_input_budget"
                    return
                from ..insight_validation import validate_units
                for repair in range(2):
                    try:
                        response, receipt = await self.steps.model(
                            job, task_id=tid, owner='M11', root_id=job['job_id'] + ':' + str(offset),
                            messages=messages, bindings=wire_binding, profile=self.model_profile('M11', version='explanation-labels-1', max_output_tokens=2048,
                                max_input_tokens=16000, max_images=0, wall_seconds=90),
                            job=job, purpose='production', root_limit=2)
                        expanded=explanation_wire(response,wire_binding,expand=True)
                        for current, paragraphs in validate_units(expanded, selected_units):
                            current.update(status='generated', paragraphs=paragraphs, reason=None,
                                           generation_mode='model',
                                           actual_attempt_ref=receipt['attempt_id'], output_repair_used=bool(repair))
                        break
                    except DomainError as exc:
                        for unit in selected_units:
                            unit['reason'] = exc.code
                        if repair or not exc.code.startswith('INSIGHT_'):
                            break
                        # Same complete unit, one local schema/citation repair.
                        # Prior model output is explicitly untrusted, never evidence.
                        revised = {**prompt, 'repair': {'failure': exc.code, 'explanation': exc.message,
                            'protocol_details': exc.details,
                            'previous_untrusted_response': locals().get('response'),
                            'instruction': '严格按response_constraints允许的kind和准确主值坐标修正。本事实单元没有claims时禁止theory_background；把有原文支持的方法说明放source_fact，不是理论。误差幅度不能声明为主值；用source组件ID和value_key，或仅保留原报误差说明。只引用正文实际说出的数值。文字简洁，不新增证据或claim，不逐条复制性质长定义。'}}
                        messages = [{'role': 'user', 'content': canonical(revised).decode()}]
                        if input_upper_bound(messages) > 16000:
                            # Preserve the full immutable fact/context unit.
                            # A failed previous output is not evidence and need
                            # not displace the facts merely to repair its schema.
                            revised['repair'].pop('previous_untrusted_response', None)
                            messages = [{'role': 'user', 'content': canonical(revised).decode()}]
                            if input_upper_bound(messages) > 16000:
                                break
                with self.repo.transaction() as conn:
                    self.repo.validate_lease(conn, job, scientific=False)
                    self.repo.put_object(conn, tid, 'insight_unit_checkpoint',
                        delivery['delivery_id'] + ':' + str(offset), 1,
                        {'delivery_id': delivery['delivery_id'], 'snapshot_ref': delivery['snapshot_ref'],
                         'unit': selected_units[0], 'knowledge_ref': {
                             'id': knowledge['manifest']['release_id'], 'version': 1,
                             'content_sha256': knowledge['manifest']['content_sha256']} if knowledge else None})

            from astroquery_ai.runtime.stages import EXECUTION_POLICY
            unit_slots = asyncio.Semaphore(EXECUTION_POLICY['insight_units'])

            async def explain_with_slot(offset):
                async with unit_slots:
                    await explain_one(offset)

            async with asyncio.TaskGroup() as group:
                for offset in range(len(units)):
                    group.create_task(explain_with_slot(offset))
        from ..insight_validation import basic_explanation, explanation_coverage
        if not selection_only:
            for unit in units:
                if unit['status'] != 'generated':
                    unit.update(status='basic', generation_mode='deterministic_basic',
                        extended_explanation='not_completed', paragraphs=basic_explanation(unit, spec))
                unit['coverage'] = explanation_coverage(unit)
        with self.repo.transaction() as conn:
            self.repo.validate_lease(conn, job, scientific=False)
            delivery = self.app.delivery.get(conn, tid, job["payload"]["delivery_id"])
            report = {
                "schema_version": "InsightReport/1",
                "report_id": "insight-" + delivery["delivery_id"],
                "delivery_id": delivery["delivery_id"],
                "snapshot_ref": delivery["snapshot_ref"],
                "status": "not_applicable"
                if not delivery["measurements"]
                else "complete"
                if units and all(u["status"] == "generated" for u in units)
                else "partial",
                "reason": reason,
                "facts": [
                    {
                        "measurement_id": r["measurement_id"],
                        "source_value": r["value"],
                        "uncertainty": r["uncertainty"],
                        "raw_value": r['raw_value'],
                        "source_unit": r['unit'],
                        "processed_value": measurement_input(delivery, r)['processed_value'],
                        "source_context": measurement_input(delivery, r)['source_statements'],
                        "context_ref": r['context_ref'],
                    }
                    for r in delivery["measurements"]
                ],
                "theory": choices,
                "units": units,
                'explanation_scope': 'property_or_evidenced_group_background',
                'complete_data_preserved': True,
                'generation_modes': sorted({u.get('generation_mode', 'not_generated') for u in units}),
                "knowledge_release_ref": {
                    "id": knowledge["manifest"]["release_id"],
                    "version": 1,
                    "content_sha256": knowledge["manifest"]["content_sha256"],
                }
                if knowledge
                else None,
                "limitations": ["缺少已核对理论依据，已保留来源事实。"]
                if reason == "kb_unavailable"
                else ["一般理论背景不代表本任务已验证相关关系。"],
            }
            reference = self.repo.put_object(conn, tid, "insight", report["report_id"], 1, report)
            self.repo.finish_job(conn, job)
            self.repo.mutate_task(
                conn,
                tid,
                insight_ref=canonical(reference).decode(),
                lifecycle="completed",
                phase="insight",
            )
            self.repo.event(
                conn, tid, "insight_updated", {"report_ref": reference, "status": report["status"]}
            )
