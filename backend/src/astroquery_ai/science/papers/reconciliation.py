"science: papers: reconciliation.py operations; existing transactions and decisions retained."

from __future__ import annotations

from pydantic import ValidationError

from astroquery_ai.runtime.codec import canonical, loads, content_hash

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.science.measurements.contracts import MeasurementProposal

from astroquery_ai.science.source_review import (
    SourceReview,
    SourceInformationReview,
    validated_group,
    source_review_blocks,
)

from astroquery_ai.science.measurements.admission_contracts import AdmissionLocatorChecks

from astroquery_ai.science.paper_admission import (
    check_local_evidence,
    preserve_parenthetical_errors,
    verification_instruction,
    admission_protocol_issues,
    protocol_repair_instruction,
    merge_locator_check,
    NATIVE_COLUMN_AUTHORITY_RULE,
    independent_proposal_view,
    native_numeric_conflict,
)

from astroquery_ai.science.prompt_contracts import property_view, proposal_rules


def reviewed_native_fields(proposal, item, blocks=(), image_pages=(), *, final=False):
    """Consume the independent original-unit/coordinate verdict, not target math."""
    check = item.assessment
    updates = {'source_quality':item.source_quality}
    literal = item.native_numeric_literal
    if item.value_match == 'different' and literal and proposal.value.kind in {'real','integer'}:
        from decimal import Decimal, InvalidOperation
        by_id = {b['block_id']:b for b in blocks}
        originals = []
        for anchor in check.role_evidence:
            originals.extend(by_id[k]['text'] for k in anchor.block_ids
                             if k in by_id and by_id[k]['page'] == anchor.page)
            if anchor.page in image_pages and anchor.quote:
                originals.append(anchor.quote)
        try:
            value = Decimal(literal.replace('−','-'))
            numbers = [m.group(0) for text in originals for m in __import__('re').finditer(
                r'(?<![\w.])[+−-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+−-]?\d+)?(?![\w.])',text)]
            if value.is_finite() and any(Decimal(n.replace('−','-')) == value for n in numbers):
                updates['value'] = proposal.value.model_copy(update={'value':str(value)})
                updates['raw_value'] = literal
        except InvalidOperation:
            pass
    if check.native_unit and check.unit_evidence and (proposal.unit is None or item.correct_native_unit):
        if not (proposal.unit is None and check.native_unit == '1'
                and item.native_representation in {'log10','ln'}):
            updates['unit'] = check.native_unit
    coordinate_evidence = [*check.quantity_evidence,
                           *(check.quantity_identity.evidence if check.quantity_identity else [])]
    if item.native_representation and coordinate_evidence:
        # QuantityIdentity anchors are the same original-source evidence used
        # by check_local_evidence, not an inferior duplicate of quantity_evidence.
        # This changes the interpretation of the unchanged native coefficient;
        # it never computes a logarithm or adopts the requested output coordinate.
        updates['representation'] = item.native_representation
        updates['representation_parameters'] = item.representation_parameters
    if final and (proposal.errors or item.corrected_errors is not None):
        from ..measurements.admission_contracts import normalized
        originals = '\n'.join(b['text'] for b in blocks)
        if item.errors_match == 'different' and item.corrected_errors is not None and all(
                normalized(e.raw_text) in normalized(originals) or proposal.page in image_pages
                for e in item.corrected_errors):
            updates['errors'] = item.corrected_errors
        elif item.errors_match != 'exact':
            updates['errors'] = [e.model_copy(update={'interpretation_state':'unresolved','values':None,
                'reason':'independent_uncertainty_transcription_not_verified'}) for e in proposal.errors]
    return proposal.model_copy(update=updates)


async def reconcile_source(self, job):
    try:
        try:
            await self.reconcile_source_once(job)
        except (DomainError, ValidationError, TimeoutError) as exc:
            code = getattr(exc,'code',type(exc).__name__)
            if not job['payload'].get('consolidated_review') or code not in {
                    'INVALID_MODEL_JSON','INCOMPLETE_MODEL_RESPONSE','PROVIDER_INACTIVITY_TIMEOUT',
                    'PROVIDER_WALL_TIMEOUT','PROVIDER_HTTP_ERROR','ValidationError','TimeoutError'}:
                raise
            # Same source/property and the same root limit of two. A successful
            # first judgment is checkpointed; a failed repair cannot mint calls.
            await self.reconcile_source_once(job)
    except (DomainError, ValidationError, TimeoutError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        if code in {
            "CAMPAIGN_BUDGET_EXHAUSTED",
            "DEFINITION_INVALIDATED",
            "DISPATCH_FORBIDDEN",
            "LEASE_EXPIRED",
            "STALE_GENERATION",
        }:
            raise
        self.close_reading_gap(job, "source_recheck_" + code)


async def reconcile_source_once(self, job):
    """Resolve repeated mentions and semantic doubts using carried source text."""
    tid, payload = (job["task_id"], job["payload"])
    bounded = bool(payload.get('consolidated_review'))
    review_image_pages, review_images = set(), []
    with self.repo.read() as conn:
        superseded = any(
            (
                content_hash(self.repo.object(conn, tid, ref["kind"], ref["id"]))
                != ref["content_sha256"]
                for ref in payload["items"]
            )
        )
    if superseded:
        with self.repo.transaction() as conn:
            self.repo.validate_lease(conn, job)
            self.repo.event(
                conn,
                tid,
                "source_recheck_superseded",
                {
                    "job_id": job["job_id"],
                    "source_id": payload["work_id"],
                    "paid_request_dispatched": False,
                },
            )
            self.repo.finish_job(conn, job)
        return
    with self.repo.read() as conn:
        spec = self.spec(conn, tid)
        quantity_identity_required=bounded and spec.get('run_policy',{}).get('reading',{}).get('quantity_identity')=='explicit/1'
        review_version=('consolidated-source-review-2' if quantity_identity_required else
                        'consolidated-source-review-1' if bounded else 'source-review-4')
        source = self.repo.object(conn, tid, "source", payload["work_id"])
        index = self.repo.object(conn, tid, "document_index", payload["work_id"])
        completed_recoveries = {
            r["candidate_id"] for r in self.repo.objects(conn, tid, "source_review_recovery")
        }
        withdrawn = {}
        for withdrawal in self.repo.objects(conn, tid, "review_withdrawal"):
            row = conn.execute(
                "SELECT status,answer FROM reviews WHERE task_id=? AND review_id=?",
                (tid, withdrawal["review_id"]),
            ).fetchone()
            if (
                withdrawal.get("schema_version") == "PausedVerifierQuestionWithdrawal/1"
                and withdrawal["source_id"] == payload["work_id"]
                and (withdrawal["candidate_ref"]["id"] not in completed_recoveries)
                and row
                and (row["status"] == "closed_unanswered")
                and (row["answer"] is None)
            ):
                withdrawn[withdrawal["candidate_ref"]["id"]] = withdrawal
        for pending in self.repo.objects(conn, tid, "candidate_pre_review_pending"):
            if (
                pending["source_id"] != payload["work_id"]
                or pending["candidate_id"] in completed_recoveries
            ):
                continue
            protected = any(
                (
                    pending["candidate_id"] in loads(row[0])["scope"].get("candidate_ids", [])
                    for row in conn.execute(
                        "SELECT payload FROM reviews WHERE task_id=? AND status<>'closed_unanswered'",
                        (tid,),
                    )
                )
            )
            if not protected:
                withdrawn[pending["candidate_id"]] = {
                    **pending,
                    "withdrawal_id": None,
                    "pre_review_owner_check": True,
                }
        proposals, originals, verifications = ({}, {}, [])
        for reference in payload["items"]:
            obj = self.repo.object(
                conn, tid, reference["kind"], reference["id"], reference["version"]
            )
            if reference["kind"] == "measurement":
                interpretation = self.repo.object(
                    conn,
                    tid,
                    "interpretation",
                    obj["interpretation_ref"]["id"],
                    obj["interpretation_ref"]["version"],
                )
                raw = interpretation["proposal"]
                verifications.append(interpretation.get("paper_verification"))
            else:
                raw = obj["proposal"]
                prior = obj.get("assembly_context", {}).get("paper_verification") or {}
                verifications.append(
                    prior if prior.get("check") else {"check": raw.get("local_admission") or {}}
                )
            proposals[reference["id"]] = preserve_parenthetical_errors(
                MeasurementProposal.model_validate(raw)
            )
            originals[reference["id"]] = obj
    pages = {p["page"]: p["text"] for p in index["pages"]}
    context_pages = set()
    context_blocks=[]
    if bounded:
        with self.repo.read() as conn:
            requests = self.repo.objects(conn,tid,'reading_context_request')
            notes=self.repo.objects(conn,tid,'reading_context_note')
        context_blocks=[b for n in notes if n['work_id']==payload['work_id'] and n['property_id']==payload.get('property_id')
                        for b in n['blocks']]
        for request in requests:
            if request['work_id'] == payload['work_id'] and request['property_id'] == payload.get('property_id'):
                page = request['request'].get('page')
                if page in pages:
                    context_pages.add(page)
    selected, omitted = source_review_blocks(
        pages, proposals.values(), verifications, spec["target"],
        byte_limit=180000 if bounded else 32000, context_pages=context_pages,context_blocks=context_blocks
    )
    if bounded:
        visual = sorted({p.page for p in proposals.values() if p.page and len(pages.get(p.page,'').strip()) < 80})
        if len(visual) > 4:
            raise DomainError('SOURCE_REVIEW_INITIAL_CAPACITY', '初始复核分组超过四个扫描页')
        import base64
        for page in visual:
            png = await self.app.parse_owned(tid, source['artifact']['artifact_id'], 'page_image', page=page)
            review_images.append({'type':'image_url','image_url':{'url':'data:image/png;base64,' + base64.b64encode(png).decode()}})
            review_image_pages.add(page)
    prompt = {
        "prompt_version": "source-review/4-evidence-bound-review",
        "native_column_authority_rule": NATIVE_COLUMN_AUTHORITY_RULE,
        "source_quality_rule": proposal_rules()["source_quality"],
        "source_quality_binding": proposal_rules()["source_quality_binding"],
        "context_scope_rule": proposal_rules()["context_scope"],
        "subject_link_rule": proposal_rules()["subject_link"],
        "instruction": "复核同一作品已经采集的候选和测量，不能新提数值、推导性质、选最佳值或扩检索。逐item_id核对实际主体、具体量、结果角色；总量不同于变化量/变化率，泛指a pulsar的示例、模拟输入、处理设定/参考线本身不能自动算目标测量。明确引用既有目标测量可保留。方法限制不等于作者否定该拟合。对同一作者结果在正文/表格/图注的重复提及，只有原文结果标识/方法/观测及引用关系能建立同一结果时才填same_results；数值相等本身不够，不同方法/历元不合并。canonical_id选作者正式报告结果的位置（有原结果表优先表行），是重复提及的原始报告定位，不是科学值偏好。保留各提及原文及误差，绝不平均、合成或丢弃误差。discriminator必须是原文可见的方法/结果名/观测标记，不得仅用数值或泛泛的DM。所有evidence使用所给block_ids；无足够证据标unresolved，不能补猜。assessment必须填写quantity_match及quantity_evidence。",
        "schema": SourceReview.model_json_schema(),
        "target": {k: spec["target"][k] for k in ("main_id", "aliases")},
        "properties": [
            property_view(b)
            for b in spec["properties"]
            if b["property_id"] in {p.property_id for p in proposals.values()}
        ],
        "items": [
            {"item_id": key, "proposal": {**independent_proposal_view(p),
                **({'claimed_errors_to_verify':[e.model_dump(mode='json') for e in p.errors]} if bounded else {})}}
            for key, p in proposals.items()
        ],
        "source_blocks": selected,
        "context_blocks_not_included": omitted,
        "source_fidelity_rule": "原文明确报告但与常见值不同的数字也按原文保留，不凭常识改写或拒绝；来源间差异原因不明就留未知。未取得的勘误不读取。",
        "quantity_origin_rule": "先检查所拟合坐标的定义和零点。相对参考值的偏移、残差、扣趋势后的基线、事件幅度，即使表头称base或与总量同单位，也不是该总量；不得加回参考值推导新测量。固定参考常数本身不是新测量。定义在远端已取得段落时结合该段落判断，缺定义标unresolved。",
        "main_admission_boundary": "这里只核实来源报告的具体量、对象及结果角色。不能因原文未报可选时标、估计方法、参考系、历元或误差置信度，就把原文已明确的具体量判unresolved；服从性质条件中retain_unknown及适用范围。原报轴向自转周期与已证实的质心计时身份不同：明确的源报告周期可保留，未知计时元数据单独保留，单位/表示及严格比较资格由M08/M09分别核验。不是把未知元数据补为已知，也不允许轨道周期、频率或相对残差代替所选量。",
        "precision_rule": "读完整句子的修饰关系。uncertainty/error/precision/resolution of a measurement所指的数值是误差幅度或精度，不是该量的主值；不能截取后面的measurement of number短语反向理解。误差与主值分别保留，不生成新主值，也不合并重复叙述的同一个误差。",
    }
    review_spec = {**spec,'properties':[b for b in spec['properties']
                   if b['property_id'] in {p.property_id for p in proposals.values()}]}
    admission = verification_instruction(review_spec, [], pages, visible_blocks=selected, compact=True)
    if bounded:
        prompt['single_review_contract'] = (
            'This is the ONE independent work/property evidence check, not a repeat of batch admission. '
            'Verify numeric transcription, actual subject/quantity, native unit/coordinate, result role, '
            'individual errors, author cautions and duplicate mentions together against original material. '
            'same_results.member_ids includes canonical_id and every other explicitly established mention; '
            'each remains an original location of the same reported result, never an independent sample. '
            'For each item explicitly give native_representation (linear/log10/etc) and '
            'value_match=exact|different|unresolved. representation_parameters are optional and only '
            'allowed when their basis is established. If different due to a transcription error, '
            'provide native_numeric_literal copied from actual role_evidence; do NOT calculate a converted value. '
            'Never calculate native log age from linear source age. '
            'For each target item give errors_match=exact|different|unresolved|not_reported. '
            'Verify each independent error amplitude/side/native coordinate and any claimed role/level against '
            'actual original text. Missing confidence/role may remain unspecified: it does not invalidate '
            'the numeric error. If the first reader miscopied/mislabelled errors, return corrected_errors '
            'with actual original raw_text and each separate component; do not average or merge them. '
            'For exact errors do not recopy the list. Unresolved errors do not invalidate a verified main value. '
            'Read log Age header and year-basis footnote together; dex is not an extra logarithm. '
            'For a native log coordinate, keep its printed coefficient distinct from its reference basis. '
            'Give coordinate_reference_unit when the actual context explicitly defines that basis unit '
            '(for example age in years); cite that original unit_evidence. For an intrinsic dimensionless '
            'log ratio with no physical reference unit use native_unit=1 when independently established. '
            'If the proposed unit is absent/mistranscribed and the ORIGINAL declaration is unambiguous, '
            'give native_unit with real unit_evidence, set correct_native_unit=true, and assess this '
            'corrected original unit. Model transcription errors are not human scientific ambiguities. '
            'Conflicting ORIGINAL declarations remain unresolved. Missing optional metadata alone '
            'does not imply author reliability warning. For native-text evidence give page and real block_ids; '
            'omit quote because the server binds the unchanged original blocks, including headers/footnotes. '
            'Only image-only evidence needs a short verbatim quote from the supplied page. '
            'Use real blocks or supplied scan images. '
            'No new values, quantities or sources, no best measurement selection.')
    for key in (
        "independent_decisions",
        "adoption_evidence_rule",
        "link_protocol",
        "decision_order",
        "scientific_review_rule",
        "identity_interpretation",
        "native_unit_check",
    ):
        prompt[key] = admission[key]
    prompt["schema"]["$defs"].update(admission["schema"]["$defs"])
    prompt["properties"] = admission["properties"]
    if quantity_identity_required:
        prompt['decision_order']=(
            'FIRST independently identify the concrete quantity actually reported in the ORIGINAL header/definition/footnote, '
            'its subject scale and native representation. Fill assessment.quantity_identity with reported_quantity, '
            'subject_scale, native_representation, original evidence and relation=same|related_or_different|requires_derivation|insufficient. '
            'THEN compare with quantity_focus and the exact selected definition. A discussion of the selected quantity '
            'does not make every related coordinate that quantity. Same underlying scientific parameter is NOT enough: '
            'a reported proxy/index/offset that requires inversion, exponentiation or a physical calibration to obtain '
            'the selected measurand is requires_derivation, not same. A simple change of units of the same quantity is '
            'different from such a derivation. A native logarithmic coefficient is same only when the exact definition '
            'selects/allows that reported coordinate; never manufacture it from a linear value. Ancillary quantities '
            'mentioned in source annotations are context to retain, not extra authorized main values. '
            'Explicitly compare the original reported quantity with the selected quantity_kind and its native boundary. '
            'Scientific illustrations, NOT word-matching rules: a magnitude difference encoding a length is not '
            'the reported length itself; an angular extent is not a spatial extent; a velocity spread is not '
            'the mean velocity. In each case reading the proxy exactly does not authorize the other measurand. '
            'Judge the actual definitions and original evidence, not these words, common values or paper topic. '
            'same maps to quantity_match=exact; related_or_different '
            'and requires_derivation map to different; insufficient maps to unresolved. Do not compute a missing quantity. '
            'ONLY AFTER identity, inspect result role, native units, independent uncertainties, cautions and repeated mentions. '
            'Do not confuse missing optional metadata with a different measurand. Source annotations apply only to their actual scope.')
        required=prompt['schema']['$defs']['AdmissionCheck']['required']
        if 'quantity_identity' not in required:required.append('quantity_identity')
    if payload.get("source_information_only"):
        prompt.update(
            schema=SourceInformationReview.model_json_schema(),
            instruction="仅修复这些已取得测量的来源限制检查。返回每个item_id及source_quality；raw_info及caution_quotes选择真实source_blocks的block_id，服务器直接绑定原文，不概述或抄省略句。逐对象、具体量、误差及方法范围判断适用性。普通引用和无相关限制可checked且caution_quotes=[]；未查或确有适用性不明保留unresolved。不要再判断主值准入，不改值、误差或人工答案。",
        )
        prompt["scope_boundary"] = (
            "这是来源采用限制检查，具体量准入和转换条件由其他步骤负责。原文未报可选误差、置信度、历元、时标或具体估计器，本身不等于来源检查没做，也不自动构成采用扣分。已查材料且未发现适用限制，可checked且caution_quotes=[]，在note保留缺失上下文。若原文明确警告误差低估、污染或低可靠性等，必须按本条作用范围保留。不要因未知时标而把已经实际检查的表头/脚注标成unresolved。"
        )
    from astroquery_ai.science.model_bindings import labels, map_fields
    item_labels = labels(list(proposals), 'I')
    review_fields = {k:item_labels for k in ('item_id','canonical_id','member_ids')}
    if bounded:
        review_fields['property_id'] = labels([b['property_id'] for b in review_spec['properties']], 'P')
    def review_messages(body):
        wire = map_fields(body, review_fields) if bounded else body
        text = canonical(wire).decode()
        return [{'role':'user','content':[{'type':'text','text':text}, *review_images] if review_images else text}]
    def expand_review(body):
        return map_fields(body, review_fields, expand=True, strict=False) if bounded else body
    response, receipt = await self.steps.model(
        job,
        task_id=tid,
        owner="M06",
        root_id=payload.get("root_id", job["job_id"]),
        messages=review_messages(prompt),
        profile=self.model_profile(
            "M06",
            "qwen3.7-plus",
            operation="paper_admission",
            version=review_version,
            max_images=4 if bounded else 0,
            source_format="pdf" if bounded else "carried_source_context",
            max_input_tokens=96000,
            max_output_tokens=8192,
            wall_seconds=480,
            inactivity_seconds=120,
        ),
        job=job,
        purpose="production",
        root_limit=2 if bounded else 3,
    )
    response = expand_review(response)
    if payload.get("source_information_only"):
        info = SourceInformationReview.model_validate(response)
        if {i.item_id for i in info.items} != set(proposals) or len(info.items) != len(proposals):
            raise DomainError("SOURCE_INFORMATION_COVERAGE", "来源检查缺少当前条目")
        from astroquery_ai.science.source_restrictions import checked_source_information

        by_id = {i.item_id: i.source_quality for i in info.items}
        outcomes = []
        for reference in payload["items"]:
            record = originals[reference["id"]]
            check = checked_source_information(
                by_id[reference["id"]],
                {b["block_id"]: b["text"] for b in selected},
                measurement_id=record["measurement_id"],
                measurement_version=record["revision"],
                evidence_refs=record["evidence_refs"],
                interpretation_ref=record["interpretation_ref"],
                check_basis={
                    "attempt_id": receipt["attempt_id"],
                    "source_id": source["source_id"],
                    "inspected_block_ids": [b["block_id"] for b in selected],
                    "scope": "per_item_target_and_quantity",
                },
            )
            outcomes.append({"item_ref": reference, "state": "not_verified", "source_check": check})
        report = {
            "schema_version": "SourceRecheck/1",
            "source_id": source["source_id"],
            "outcomes": outcomes,
            "same_results": [],
            "limitations": [],
            "attempt_id": receipt["attempt_id"],
            "source_information_only": True,
            "context_blocks_not_included": omitted,
            "new_source_requests": 0,
        }
        with self.repo.transaction() as conn:
            self.repo.validate_lease(conn, job)
            ref = self.repo.put_object(conn, tid, "source_recheck", job["job_id"], 1, report)
            self.repo.enqueue(conn, tid, "M07", "apply_source_recheck", {"recheck_ref": ref})
            self.repo.finish_job(conn, job, ref)
        return
    from astroquery_ai.science.source_review import source_review_outcome
    review, schema_errors = source_review_outcome(response)
    by_item = {item.item_id: item for item in review.items}
    assessment_receipts = {key: receipt for key in by_item}
    repair_ids = set(proposals) - set(by_item)
    for key, item in by_item.items():
        if key not in proposals:
            raise DomainError("SOURCE_RECHECK_SCOPE", "作品复核返回了范围外条目")
        if bounded:
            if (quantity_identity_required and item.assessment.quantity_identity is None
                    and item.assessment.subject!='other' and item.assessment.quantity_match!='different'
                    and item.assessment.result_role in {'reported_result','adopted_measurement','unresolved'}):
                repair_ids.add(key)
            proposals[key] = reviewed_native_fields(proposals[key], item, selected, review_image_pages)
            if (item.assessment.subject == 'target' and item.assessment.quantity_match == 'exact'
                    and item.assessment.result_role in {'reported_result','adopted_measurement'}
                    and (item.native_representation is None or item.value_match == 'unresolved')):
                repair_ids.add(key)
            if (proposals[key].errors and item.errors_match is None and item.assessment.subject == 'target'
                    and item.assessment.quantity_match == 'exact'):
                repair_ids.add(key)
            if (item.assessment.subject=='target' and item.assessment.quantity_match=='exact'
                    and item.assessment.native_unit=='dex' and item.native_representation!='log10'):
                repair_ids.add(key)
            if (item.assessment.subject=='target' and item.assessment.quantity_match=='exact'
                    and item.assessment.result_role in {'reported_result','adopted_measurement'}):
                from ..source_restrictions import checked_source_information
                info=checked_source_information(item.source_quality,{b['block_id']:b['text'] for b in selected},
                    measurement_id=key,measurement_version=1,evidence_refs=[],interpretation_ref={})
                if item.source_quality is None or item.source_quality.state=='checked' and info['state']!='checked':
                    repair_ids.add(key)
        check = item.assessment
        if (
            check.subject != "unresolved"
            and check.result_role != "unresolved"
            and (check.quantity_match in {"exact", "different"})
        ):
            bound = check_local_evidence(
                proposals[key],
                check,
                spec["target"],
                pages,
                receipt,
                visible_blocks=selected,
                image_pages=review_image_pages,
                require_quantity=True,
                require_units=True,
                property_binding=next((b for b in spec['properties'] if b['property_id']==proposals[key].property_id),None),
            )
            if bound["state"] == "unresolved" and bound['reason'] != 'scientific_ambiguity':
                repair_ids.add(key)
    locator_ids = sorted(
        (
            key
            for key in repair_ids
            if key in by_item
            and admission_protocol_issues(
                proposals[key], by_item[key].assessment, spec["target"], pages, selected
            )
        )
    )
    if repair_ids and set(locator_ids) == repair_ids and not bounded:
        repair_prompt = protocol_repair_instruction(
            spec,
            [proposals[key] for key in locator_ids],
            [by_item[key].assessment for key in locator_ids],
            [
                admission_protocol_issues(
                    proposals[key], by_item[key].assessment, spec["target"], pages, selected
                )
                for key in locator_ids
            ],
            pages,
            selected,
        )
        try:
            repaired, repair_receipt = await self.steps.model(
                job,task_id=tid,owner="M06",root_id=payload.get("root_id", job["job_id"]),
                messages=review_messages(repair_prompt),
                profile=self.model_profile("M06","qwen3.7-plus",operation="paper_admission",
                    version=review_version,
                    max_images=4 if bounded else 0,source_format="pdf" if bounded else "carried_source_context",
                    max_input_tokens=96000,max_output_tokens=8192,wall_seconds=480,inactivity_seconds=120),
                job=job,purpose="production",root_limit=2 if bounded else 3)
        except (DomainError,ValidationError,TimeoutError) as exc:
            code=getattr(exc,'code',type(exc).__name__)
            if (not bounded or code.startswith('PROFILE_') or code in {
                    'LEASE_EXPIRED','STALE_GENERATION','DEFINITION_INVALIDATED','DISPATCH_FORBIDDEN'}):
                raise
            repaired={'items':[],'limitations':['local_repair_failed:'+code]}
            repair_receipt=receipt
            review=review.model_copy(update={'limitations':[*review.limitations,'local_repair_failed:'+code]})
        seen = set()
        for locator in AdmissionLocatorChecks.model_validate(repaired).results:
            if locator.index >= len(locator_ids) or locator.index in seen:
                raise DomainError("SOURCE_RECHECK_SCOPE", "主体定位修复返回范围外或重复条目")
            seen.add(locator.index)
            key = locator_ids[locator.index]
            by_item[key] = by_item[key].model_copy(
                update={"assessment": merge_locator_check(by_item[key].assessment, locator)}
            )
            assessment_receipts[key] = repair_receipt
        review = review.model_copy(update={"items": list(by_item.values())})
    elif repair_ids:
        repair_prompt = {
            **prompt,
            "items": [item for item in prompt["items"] if item["item_id"] in repair_ids],
            "repair_reason": "Missing item or semantic verdict without valid original evidence binding.",
            'schema_diagnostics':schema_errors,
            'source_information_feedback':(
                'Each eligible target item needs the source_quality check from the already supplied original '
                'headers/notes/context. raw_info/caution_quotes select actual block IDs only; do not prefix IDs '
                'to paraphrases. Checked with no applicable caution is allowed only after inspecting real material. '
                'Missing optional confidence/method, ordinary citation or a different method is not itself a caution. '
                'If a real scope/limitation remains uncertain, keep unresolved; do not manufacture checked or a score.'),
            'native_unit_feedback':(
                'For a verified native logarithm of a physical age, native_unit is the ORIGINAL explicitly stated '
                'reference unit (e.g. yr when the actual text defines age in years), not another logarithm. '
                'For an evidenced intrinsic dimensionless log-ratio coordinate, native_unit=1 with original '
                'definition/header unit_evidence; it is not an invented printed physical unit. '
                'representation_parameters may simply be null when absolute parameters are unavailable; '
                'never put a textual solar reference into a numeric reference_value. '
                'Keep unknowns for genuinely missing declarations. No arithmetic or new scientific defaults.'),
            'coordinate_classification_feedback':(
                'A source dex coefficient is already on a log10 axis; linear would mean the underlying '
                'ratio, not its printed coefficient. Resolve this from the original definition/header. '
                'Do not exponentiate or take another logarithm of the reported value.'),
            "previous_untrusted_items": [
                i.model_dump(mode="json") for i in review.items if i.item_id in repair_ids
            ],
            'verification_feedback': {key: {k: v[k] for k in ('reason', 'native_unit', 'claimed_unit') if k in v}
                for key in repair_ids if key in by_item
                for v in [check_local_evidence(proposals[key], by_item[key].assessment, spec['target'], pages,
                    receipt, visible_blocks=selected, image_pages=review_image_pages, require_quantity=True, require_units=True,
                    property_binding=next((b for b in spec['properties'] if b['property_id']==proposals[key].property_id),None))]},
            "instruction": "只修复这些item_id，每项恰好一次。引用实际source_blocks的正确page和block_ids，不自造ID。核实印出主体与查询目标是否相同，原文无候选值时明确not_reported；不因缺可选元数据否定已明确的原报量。若确无科学依据则unresolved，不猜。返回SourceReview JSON；不新增其他条目或same_results。",
        }
        try:
            repaired, repair_receipt = await self.steps.model(
                job,task_id=tid,owner="M06",root_id=payload.get("root_id", job["job_id"]),
                messages=review_messages(repair_prompt),
                profile=self.model_profile("M06","qwen3.7-plus",operation="paper_admission",
                    version=review_version,
                    max_images=4 if bounded else 0,source_format="pdf" if bounded else "carried_source_context",
                    max_input_tokens=96000,max_output_tokens=8192,wall_seconds=480,inactivity_seconds=120),
                job=job,purpose="production",root_limit=2 if bounded else 3)
        except (DomainError,ValidationError,TimeoutError) as exc:
            code=getattr(exc,'code',type(exc).__name__)
            if (not bounded or code.startswith('PROFILE_') or code in {
                    'LEASE_EXPIRED','STALE_GENERATION','DEFINITION_INVALIDATED','DISPATCH_FORBIDDEN'}):
                raise
            repaired={'items':[],'limitations':['local_repair_failed:'+code]}
            repair_receipt=receipt
            review=review.model_copy(update={'limitations':[*review.limitations,'local_repair_failed:'+code]})
        repaired = expand_review(repaired)
        fixed, repair_schema_errors = source_review_outcome(repaired)
        if not bounded and set((i.item_id for i in fixed.items)) - repair_ids:
            raise DomainError("SOURCE_RECHECK_SCOPE", "作品复核修复越过原始失败项")
        if bounded:
            fixed=fixed.model_copy(update={'items':[i for i in fixed.items if i.item_id in repair_ids]})
        by_item.update({i.item_id: i for i in fixed.items})
        assessment_receipts.update({i.item_id: repair_receipt for i in fixed.items})
        review = review.model_copy(update={"items": list(by_item.values())})
    checks, source_quality = ({}, {})
    for item in review.items:
        if item.item_id in proposals:
            checks[item.item_id] = item.assessment if item.item_id not in checks else None
            source_quality[item.item_id] = item.source_quality
    outcomes, eligible, mapped, recoveries = ([], set(), {}, [])
    for reference in payload["items"]:
        key = reference["id"]
        proposal = proposals[key]
        if bounded and key in by_item:
            proposal = reviewed_native_fields(proposal, by_item[key], selected, review_image_pages,final=True)
            proposals[key] = proposal
        if reference["kind"] == "candidate" and key in withdrawn and source_quality.get(key):
            proposal = proposal.model_copy(update={"source_quality": source_quality[key]})
        assessment = checks.get(key)
        assessment_receipt = assessment_receipts.get(key, receipt)
        if assessment:
            proposal = proposal.model_copy(
                update={
                    "subject_role": assessment.subject,
                    "result_role": assessment.result_role,
                    "ambiguity": None,
                }
            )
        verification = check_local_evidence(
            proposal,
            assessment,
            spec["target"],
            pages,
            assessment_receipt,
            visible_blocks=selected,
            image_pages=review_image_pages,
            require_quantity=True,
            require_units=True,
            property_binding=next((b for b in spec['properties'] if b['property_id']==proposal.property_id),None),
        )
        if (quantity_identity_required and verification['state']!='rejected'
                and (assessment is None or assessment.quantity_identity is None)):
            verification.update(state='unresolved',reason='structured_quantity_identity_not_verified')
        if bounded and verification['state'] == 'passed':
            item = by_item.get(key)
            if not item or not item.native_representation or item.value_match == 'unresolved':
                verification.update(state='unresolved', reason='native_value_or_coordinate_not_verified')
            elif item.value_match == 'different' and (not item.native_numeric_literal or proposal.raw_value != item.native_numeric_literal):
                verification.update(state='unresolved', reason='native_numeric_correction_not_grounded')
            elif item.value_match == 'different' and native_numeric_conflict(proposal):
                verification.update(state='rejected', reason='native_numeric_coordinate_changed')
        outcome = {
            "item_ref": reference,
            "state": verification["state"],
            "verification": verification,
        }
        if reference["kind"] == "measurement":
            from astroquery_ai.science.source_restrictions import checked_source_information

            record = originals[key]
            outcome["source_check"] = checked_source_information(
                source_quality.get(key),
                {b["block_id"]: b["text"] for b in selected},
                measurement_id=key,
                measurement_version=record["revision"],
                evidence_refs=record["evidence_refs"],
                interpretation_ref=record["interpretation_ref"],
                check_basis={
                    "attempt_id": assessment_receipt["attempt_id"],
                    "source_id": source["source_id"],
                    "inspected_block_ids": [b["block_id"] for b in selected],
                    "omitted_block_ids": omitted,
                    "scope": "per_item_target_and_quantity",
                },
            )
        if reference["kind"] == "candidate":
            withdrawal = withdrawn.get(key)
            if (
                withdrawal
                and {k: reference[k] for k in ("id", "version", "content_sha256")}
                == withdrawal["candidate_ref"]
                and (not originals[key].get("current_measurement_ref"))
            ):
                assembly = {
                    **originals[key]["assembly_context"],
                    "spec": spec,
                    "batch_id": job["job_id"],
                    "paper_verification": verification,
                }
                try:
                    result = self.extractor.assemble(proposal=proposal, **assembly)
                except (ValidationError,DomainError) as exc:
                    if isinstance(exc,DomainError) and exc.code not in {'PROPERTY_VALUE_TYPE','SOURCE_VALUE_TRANSCRIPTION_MISMATCH'}:
                        raise
                    # A malformed optional component in one item cannot erase
                    # other independently checked results from this source.
                    result={**originals[key], 'state':'rejected' if isinstance(exc,DomainError) else 'review_candidate',
                        'reason':exc.code if isinstance(exc,DomainError) else 'source_assembly_schema_unresolved',
                        'proposal':proposal.model_dump(mode='json'),'assembly_context':assembly,
                        'owner_schema_diagnostics':[{'reason':exc.code}] if isinstance(exc,DomainError) else
                            [{'loc':list(e['loc']),'type':e['type']} for e in exc.errors()]}
                if bounded and result['state'] == 'admitted':
                    record = result['measurement']
                    mapped[key] = {'id':record['measurement_id'], 'version':record['revision'],
                                   'content_sha256':record['content_sha256']}
                    eligible.add(key)
                recoveries.append((key, result, withdrawal, assessment_receipt))
                outcome["state"] = (
                    "owner_rechecked_before_human"
                    if withdrawal.get("pre_review_owner_check")
                    else "owner_rechecked_after_pause"
                )
                outcomes.append(outcome)
                continue
            outcome["state"] = "awaiting_human"
            outcomes.append(outcome)
            continue
        if (
            verification["state"] == "unresolved"
            and assessment
            and (assessment.subject != "unresolved")
            and (assessment.result_role != "unresolved")
            and (assessment.quantity_match in {"exact", "different"})
        ):
            outcome.update(state="not_verified", failure_kind="source_recheck_evidence_binding")
        if assessment is None:
            outcome.update(
                state="not_verified", failure_kind="source_recheck_missing_item_after_repair"
            )
        if outcome["state"] == "passed":
            mapped[key] = {k: reference[k] for k in ("id", "version", "content_sha256")}
            if key in mapped:
                eligible.add(key)
        outcomes.append(outcome)
    raw_proposals = {key: p.model_dump(mode="json") for key, p in proposals.items()}
    groups, assigned = ([], set())
    block_map = {b["block_id"]: b for b in selected}
    for group in review.same_results:
        valid = validated_group(group, raw_proposals, eligible, block_map)
        if valid and (not assigned.intersection(valid["member_ids"])):
            assigned.update(valid["member_ids"])
            groups.append(
                {
                    **valid,
                    "canonical_ref": mapped[valid["canonical_id"]],
                    "member_refs": [mapped[key] for key in valid["member_ids"]],
                }
            )
    report = {
        "schema_version": "SourceRecheck/1",
        "source_id": source["source_id"],
        "outcomes": outcomes,
        "same_results": groups,
        "limitations": review.limitations,
        "attempt_id": receipt["attempt_id"],
        "local_repair_attempt_ids": sorted(
            {
                r["attempt_id"]
                for r in assessment_receipts.values()
                if r["attempt_id"] != receipt["attempt_id"]
            }
        ),
        "context_blocks_not_included": omitted,
        "new_source_requests": 0,
    }
    with self.repo.transaction() as conn:
        self.repo.validate_lease(conn, job)
        for key, result, withdrawal, assessment_receipt in recoveries:
            self.commit_candidates(conn, tid, [result], job["job_id"])
            self.repo.put_object(
                conn,
                tid,
                "source_review_recovery",
                "pause-recovery-" + key,
                1,
                {
                    "schema_version": "PreReviewOwnerRecovery/1"
                    if withdrawal.get("pre_review_owner_check")
                    else "PausedVerifierOwnerRecovery/1",
                    "owner": "M06",
                    "candidate_id": key,
                    "candidate_ref": withdrawal["candidate_ref"],
                    "withdrawal_id": withdrawal["withdrawal_id"],
                    "source_id": payload["work_id"],
                    "state": result["state"],
                    "verification_attempt_id": assessment_receipt["attempt_id"],
                    "batch_id": job["job_id"],
                    "human_answer_applied": False,
                    "raw_value_reextracted": False,
                    "new_source_requests": 0,
                },
            )
        ref = self.repo.put_object(conn, tid, "source_recheck", job["job_id"], 1, report)
        missing_info = [
            o["item_ref"]
            for o in outcomes
            if o["item_ref"]["kind"] == "measurement"
            and o.get("source_check", {}).get("state") != "checked"
            and (
                not o.get("source_check", {}).get("information")
                or o["source_check"]["information"]["state"] == "checked"
            )
        ]
        if missing_info and not bounded:
            self.repo.enqueue(
                conn,
                tid,
                "M06",
                "source_reconcile",
                {
                    "work_id": source["source_id"],
                    "items": missing_info,
                    "source_information_only": True,
                    "source_info_repair_of": ref,
                },
            )
        self.repo.enqueue(conn, tid, "M07", "apply_source_recheck", {"recheck_ref": ref})
        self.repo.finish_job(conn, job, ref)
