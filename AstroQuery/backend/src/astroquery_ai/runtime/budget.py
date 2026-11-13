"""Persistent currency reservation. One yuan = 1,000,000 integer micro-yuan."""

from __future__ import annotations

from dataclasses import dataclass

from .codec import canonical, content_hash, digest, loads, new_id, utcnow
from .errors import DomainError
from .models import TERMINAL


@dataclass(frozen=True)
class Price:
    input_micros_per_token: int
    output_micros_per_token: int
    # Prices such as 0.8 micro-yuan/token are represented as integer tenths.
    denominator: int = 10
    version: str = "bailian-beijing-list-2026-10-25"

    def cost(self, inputs: int, outputs: int) -> int:
        numerator = inputs * self.input_micros_per_token + outputs * self.output_micros_per_token
        return (numerator + self.denominator - 1) // self.denominator


def price_for(model: str, input_bound: int) -> Price:
    if model == "qwen3.8-flash":
        return Price(8, 27)
    if model == "qwen3.7-plus":
        return Price(20, 80) if input_bound <= 256_000 else Price(60, 240)
    if model == "qwen3.8-max":
        return Price(120, 360)
    raise DomainError("UNPRICED_MODEL", "模型没有已登记价格，禁止收费调用", 422, model=model)


class Budget:
    def __init__(
        self, repository, campaign_id="software-validation-2026-10-25", cap_micros=80_000_000
    ):
        if type(cap_micros) is not int or cap_micros < 0:
            raise ValueError("campaign cap must be a nonnegative integer")
        self.repository, self.campaign_id = repository, campaign_id
        with repository.transaction() as conn:
            old = conn.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,)
            ).fetchone()
            if old and old["cap_micros"] != cap_micros:
                raise DomainError("BUDGET_IMMUTABLE", "不能通过重启修改已有验证额度")
            if not old:
                if conn.execute("SELECT 1 FROM campaigns LIMIT 1").fetchone():
                    raise DomainError("CAMPAIGN_ALREADY_EXISTS", "不能换验证活动编号来重置额度")
                conn.execute(
                    "INSERT INTO campaigns(campaign_id,cap_micros,smoke_cap_micros,created_at) VALUES(?,?,?,?)",
                    (campaign_id, cap_micros, min(5_000_000, cap_micros), utcnow()),
                )

    def uncapped(self, conn):
        row = conn.execute("SELECT payload FROM settings WHERE key='campaign_amount_authorization'").fetchone()
        if not row:
            return False
        grant = loads(row[0])
        return (grant.get('schema_version') == 'CampaignAmountAuthorization/1'
            and grant.get('campaign_id') == self.campaign_id
            and grant.get('mode') == 'uncapped' and grant.get('authorized_by') == 'user')

    @staticmethod
    def _used(conn, campaign_id, smoke_only=False) -> int:
        query = "SELECT coalesce(sum(CASE WHEN status IN ('settled','not_dispatched') THEN actual_micros ELSE reserved_micros END),0) FROM attempts WHERE campaign_id=?"
        if smoke_only:
            query += " AND smoke=1"
        return conn.execute(query, (campaign_id,)).fetchone()[0]

    def summary(self) -> dict:
        with self.repository.read() as conn:
            campaign = dict(
                conn.execute(
                    "SELECT * FROM campaigns WHERE campaign_id=?", (self.campaign_id,)
                ).fetchone()
            )
            campaign["committed_micros"] = self._used(conn, self.campaign_id)
            uncapped = self.uncapped(conn)
            campaign["amount_cap_mode"] = "uncapped_by_user_authorization" if uncapped else "limited"
            campaign["cost_basis"] = "list_price_usage_estimate_not_discounted_provider_bill"
            campaign["effective_cap_micros"] = None if uncapped else min(campaign["cap_micros"], campaign["funded_cap_micros"])
            campaign["remaining_micros"] = None if uncapped else max(0, campaign["effective_cap_micros"] - campaign["committed_micros"])
            campaign["unknown_count"] = conn.execute(
                "SELECT count(*) FROM attempts WHERE campaign_id=? AND status='unknown'",
                (self.campaign_id,),
            ).fetchone()[0]
            campaign["actual_micros"] = conn.execute(
                "SELECT coalesce(sum(actual_micros),0) FROM attempts WHERE campaign_id=? AND status='settled'",
                (self.campaign_id,),
            ).fetchone()[0]
            return campaign

    def reserve(
        self,
        *,
        task_id: str,
        owner: str,
        model: str,
        root_id: str,
        request: dict,
        input_bound: int,
        output_bound: int,
        job: dict | None = None,
        smoke=False,
        root_limit=3,
        profile_state="trial",
        purpose="calibration",
        wall_bound_seconds=480,
        defer_for_settlement=False,
    ) -> dict:
        if (
            type(input_bound) is not int
            or type(output_bound) is not int
            or input_bound <= 0
            or output_bound <= 0
        ):
            raise DomainError("MISSING_COST_BOUND", "调用前必须有有限的输入输出上界", 422)
        import math

        if (
            type(wall_bound_seconds) not in {int, float}
            or not math.isfinite(wall_bound_seconds)
            or not 0 < wall_bound_seconds <= 480
            or type(root_limit) is not int
            or not 1 <= root_limit <= 1200
        ):
            raise DomainError("INVALID_ATTEMPT_LIMIT", "调用必须有有效且有限的时间与次数上限", 422)
        if profile_state != "validated" and purpose not in {'calibration', 'pilot', 'verification', 'material_summary'}:
            raise DomainError("PROFILE_NOT_VALIDATED", "运行配置尚未校准，只允许有界校准调用")
        # M04 uses the separately qualified bibliographic expression/relevance
        # operation. It still has no measurement admission authority.
        if owner in {"M05", "M07", "M09", "M10", "M12"}:
            raise DomainError("MODEL_CALL_FORBIDDEN", "该模块没有模型调用权限")
        price = price_for(model, input_bound)
        reservation = price.cost(input_bound, output_bound)
        with self.repository.transaction() as conn:
            enabled = conn.execute(
                "SELECT payload FROM settings WHERE key='provider_dispatch_enabled'"
            ).fetchone()
            if enabled and bytes(enabled[0]) == b"false":
                raise DomainError("PROVIDER_DISABLED", "已检测到费用上界问题，当前禁止新调用")
            task = self.repository.task(conn, task_id)
            self.repository.guard_definitions(conn, task)
            material_summary = False
            if purpose == "material_summary":
                from astroquery_ai.science.material_summaries import MODEL, PROFILE, permit_matches
                material_summary = (
                    profile_state == PROFILE.state and model == MODEL and not smoke and root_limit == 1
                    and input_bound <= PROFILE.max_input_tokens and output_bound <= PROFILE.max_output_tokens
                    and wall_bound_seconds <= PROFILE.wall_seconds and request.get("enable_thinking") is False
                    and permit_matches(self.repository, conn, task, owner, model, root_id,
                                       messages=request.get("messages"))
                )
                if not material_summary:
                    raise DomainError("MATERIAL_SUMMARY_SCOPE", "调用与已保存资料总结输入不匹配")
            if purpose == "verification":
                from .science_capabilities import verification_scope
                if not task["query_ref"]:
                    raise DomainError("VERIFICATION_SCOPE", "固定输入验证缺少冻结请求")
                ref = loads(task["query_ref"])
                spec = self.repository.object(conn, task_id, "confirmed_query", ref["id"], ref["version"])
                if verification_scope(self.repository, conn, task_id, spec) is None:
                    raise DomainError("VERIFICATION_SCOPE", "固定输入验证范围未登记")
            if purpose == "calibration":
                scopes = self.repository.objects(conn, task_id, "calibration_scope")
                if scopes and "maximum_cost_micros" in scopes[0]:
                    scope = scopes[0]
                    related = sorted({task_id, *scope.get("related_task_ids", [])})
                    marks = ",".join("?" for _ in related)
                    spent = conn.execute(
                        "SELECT count(*),coalesce(sum(coalesce(actual_micros,reserved_micros)),0) FROM attempts WHERE task_id IN ("
                        + marks + ") AND status<>'not_dispatched'", related,
                    ).fetchone()
                    if (spent[0] >= scope["maximum_model_calls"]
                            or spent[1] + reservation > scope["maximum_cost_micros"]):
                        raise DomainError("CALIBRATION_CASE_BUDGET", "同一真实案例的累计验证预算已满")
            if purpose == 'pilot':
                scope = self.repository.object(conn, task_id, 'pilot_scope', task_id)
                if scope.get('schema_version') != 'IsolatedLivePilot/1' or scope.get('synthetic') is not False or scope.get('formal_release_ready') is not False or model not in scope.get('allowed_models', {}).get(owner, []):
                    raise DomainError('PILOT_SCOPE_INVALID', '试运行的对象、角色或模型尚未登记')
                related = sorted({task_id, *scope.get('related_task_ids', [])})
                related = sorted(set(related) | {row[0] for row in conn.execute(
                    "SELECT DISTINCT o.task_id FROM objects o,json_each(json_extract(CAST(o.payload AS TEXT),'$.related_task_ids')) r WHERE o.kind='calibration_scope' AND r.value=? AND json_extract(CAST(o.payload AS TEXT),'$.maximum_cost_micros')=?",
                    (task_id, scope['maximum_cost_micros']),
                )})
                marks = ','.join('?' for _ in related)
                current = conn.execute("SELECT count(*),coalesce(sum(CASE WHEN status='settled' THEN actual_micros ELSE reserved_micros END),0) FROM attempts WHERE task_id IN (" + marks + ") AND status<>'not_dispatched'", related).fetchone()
                if current[0] >= scope['maximum_model_calls'] or current[1] + reservation > scope['maximum_cost_micros']:
                    raise DomainError('PILOT_BUDGET_EXHAUSTED', '本阶段登记的累计调用或费用额度已用完')
            permitted_kind = (
                task["kind"] == "live" or task["kind"] == "validation" and purpose == "calibration"
            )
            read_only_summary = (material_summary and not job and task["science_state"] == "sealed"
                                 and task["lifecycle"] in {"completed", "budget_exhausted"})
            if not permitted_kind or not read_only_summary and task["lifecycle"] in TERMINAL | {
                "paused",
                "interrupted",
                "pausing",
                "cancelling",
                "waiting_input",
                "waiting_review",
            }:
                raise DomainError("DISPATCH_FORBIDDEN", "当前状态不允许模型调用")
            report_recheck = None
            if task["science_state"] == "sealed" and owner != "M11":
                from .report_recheck import allowed
                report_recheck = allowed(self.repository, conn, task, owner, job, request, root_id, root_limit)
            if task["science_state"] == "sealed" and owner != "M11" and not report_recheck:
                raise DomainError("SCIENCE_SEALED", "科学处理已封口")
            if job:
                self.repository.validate_lease(conn, job, scientific=owner != "M11" and not report_recheck)
            if purpose == "production" and owner != "M01" and not task["query_ref"]:
                raise DomainError("QUERY_NOT_CONFIRMED", "科学调用必须绑定已冻结请求")
            if any(
                item["owner"] == owner
                for item in self.repository.objects(conn, task_id, "branch_closure")
            ):
                raise DomainError("MODULE_MODEL_LIMIT", "该消费分支已因额度终态关闭", owner=owner)

            # Normal work is bounded by its finite inputs, per-request limits
            # and finite recovery, not accumulated module/work token clocks.
            work_scope = report_recheck['source_id'] if report_recheck else (job or {}).get("payload", {}).get("work_id")
            if owner == "M06" and purpose in {"production", "pilot"}:
                if (job or {}).get('kind')=='compare_results':
                    # Comparison consumes already checked records across sources,
                    # not a fabricated single PDF/work. Bind its finite scope to
                    # one actually confirmed property in this frozen request.
                    query_ref=loads(task['query_ref'])
                    spec=self.repository.object(conn,task_id,'confirmed_query',query_ref['id'],query_ref['version'])
                    pid=job['payload'].get('property_id')
                    if pid not in {b['property_id'] for b in spec['properties']}:
                        raise DomainError('WORK_BUDGET_SCOPE_MISSING','对照缺少已确认性质范围')
                    work_scope='property-comparison:'+pid
                if not work_scope:
                    raise DomainError("WORK_BUDGET_SCOPE_MISSING", "正文读取缺少具体作品范围")
                from .run_policy import frozen_policy
                policy = frozen_policy(self.repository, conn, task_id) or {}
                work_limit = 4 if policy.get('reading', {}).get('maximum_attempts') == 2 else 1
                if conn.execute(
                    "SELECT count(*) FROM attempts WHERE task_id=? AND owner='M06' AND work_scope=? AND status IN ('reserved','dispatched')",
                    (task_id, work_scope),
                ).fetchone()[0] >= work_limit:
                    from .throughput import DispatchDeferred
                    raise DispatchDeferred('work-model-slots:'+work_scope, 0.5)
            campaign = conn.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?", (self.campaign_id,)
            ).fetchone()
            if not smoke and not campaign["smoke_passed"]:
                raise DomainError("SMOKE_NOT_PASSED", "先完成5元以内的协议验证")
            count = conn.execute(
                "SELECT count(*) FROM attempts WHERE campaign_id=? AND task_id=? AND root_id=? AND status<>'not_dispatched'",
                (self.campaign_id, task_id, root_id),
            ).fetchone()[0]
            if count >= root_limit:
                raise DomainError("ATTEMPT_LIMIT", "该逻辑事项调用次数已用完")
            if not self.uncapped(conn):
                limit = min(campaign["cap_micros"], campaign["funded_cap_micros"])
                committed = self._used(conn, self.campaign_id)
                if committed + reservation > limit:
                    if defer_for_settlement:
                        in_flight = conn.execute(
                            "SELECT coalesce(sum(reserved_micros),0) FROM attempts "
                            "WHERE campaign_id=? AND status IN ('reserved','dispatched')",
                            (self.campaign_id,),
                        ).fetchone()[0]
                        if committed - in_flight + reservation <= limit:
                            from .throughput import DispatchDeferred

                            raise DispatchDeferred("campaign-model-settlement", 2)
                    raise DomainError(
                        "CAMPAIGN_BUDGET_EXHAUSTED",
                        "本轮验证剩余额度不足",
                        requested_micros=reservation,
                    )
            if (
                smoke
                and self._used(conn, self.campaign_id, True) + reservation
                > campaign["smoke_cap_micros"]
            ):
                raise DomainError("SMOKE_BUDGET_EXHAUSTED", "协议验证额度不足")
            attempt_id = new_id()
            conn.execute(
                """INSERT INTO attempts(attempt_id,campaign_id,task_id,job_id,root_id,owner,model,request_hash,price_version,status,reserved_micros,input_bound,output_bound,smoke,created_at,generation,work_scope,wall_bound_seconds)
                VALUES(?,?,?,?,?,?,?,?,?,'reserved',?,?,?,?,?,?,?,?)""",
                (
                    attempt_id,
                    self.campaign_id,
                    task_id,
                    job["job_id"] if job else None,
                    root_id,
                    owner,
                    model,
                    digest(request),
                    price.version,
                    reservation,
                    input_bound,
                    output_bound,
                    int(smoke),
                    utcnow(),
                    task["generation"],
                    work_scope,
                    wall_bound_seconds,
                ),
            )
            self.repository.event(
                conn,
                task_id,
                "budget_changed",
                {"attempt_id": attempt_id, "state": "reserved", "reserved_micros": reservation},
            )
            return dict(
                conn.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            )

    def dispatch(self, attempt_id: str, *, authorize=None):
        try:
            return self._dispatch(attempt_id, authorize=authorize)
        except BaseException:
            # The transport has not been entered if this guard fails. Unlike an
            # unknown response, this reservation is provably zero spend.
            with self.repository.transaction() as conn:
                conn.execute(
                    "UPDATE attempts SET status='not_dispatched',actual_micros=0,settled_at=? WHERE attempt_id=? AND campaign_id=? AND status='reserved'",
                    (utcnow(), attempt_id, self.campaign_id),
                )
            raise

    def _dispatch(self, attempt_id: str, *, authorize=None):
        with self.repository.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM attempts WHERE attempt_id=? AND campaign_id=?",
                (attempt_id, self.campaign_id),
            ).fetchone()
            if row is None or row["status"] != "reserved":
                raise DomainError("INVALID_ATTEMPT", "请求没有有效预留")
            task = self.repository.task(conn, row["task_id"])
            self.repository.guard_definitions(conn, task)
            summary_permit = False
            material_call = row["root_id"].startswith("material-summary-call-")
            if material_call:
                from astroquery_ai.science.material_summaries import permit_matches
                summary_permit = permit_matches(self.repository, conn, task, row["owner"], row["model"], row["root_id"])
            read_only_summary = (summary_permit and not row["job_id"] and task["science_state"] == "sealed"
                                 and task["lifecycle"] in {"completed", "budget_exhausted"})
            if task["generation"] != row["generation"] or (material_call and not summary_permit) or not read_only_summary and task["lifecycle"] in TERMINAL | {
                "paused",
                "pausing",
                "interrupted",
                "cancelling",
                "waiting_input",
                "waiting_review",
            }:
                conn.execute(
                    "UPDATE attempts SET status='not_dispatched',actual_micros=0,settled_at=? WHERE attempt_id=?",
                    (utcnow(), attempt_id),
                )
                # Commit the zero settlement before the caller observes the refusal.
                refused = True
            else:
                if authorize is not None:
                    authorize(conn, row)
                conn.execute(
                    "UPDATE attempts SET status='dispatched',dispatched_at=? WHERE attempt_id=?",
                    (utcnow(), attempt_id),
                )
                refused = False
        if refused:
            raise DomainError("DISPATCH_FORBIDDEN", "任务已停止派发新请求")

    def settle(
        self, attempt_id: str, *, input_tokens: int | None, output_tokens: int | None, receipt: dict
    ):
        with self.repository.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM attempts WHERE attempt_id=? AND campaign_id=?",
                (attempt_id, self.campaign_id),
            ).fetchone()
            if row is None or row["status"] not in {"dispatched", "unknown", "settled"}:
                raise DomainError("INVALID_SETTLEMENT", "请求尚未派发或不属于此账本")
            if row["status"] == "settled":
                if (row["input_tokens"], row["output_tokens"]) != (input_tokens, output_tokens):
                    raise DomainError("SETTLEMENT_CONFLICT", "同一调用不能重复结算不同用量")
                return
            known = all(type(n) is int and n >= 0 for n in (input_tokens, output_tokens))
            actual = (
                price_for(row["model"], input_tokens).cost(input_tokens, output_tokens)
                if known
                else None
            )
            status = "settled" if known else "unknown"
            conn.execute(
                "UPDATE attempts SET status=?,actual_micros=?,input_tokens=?,output_tokens=?,receipt=?,settled_at=? WHERE attempt_id=?",
                (
                    status,
                    actual,
                    input_tokens,
                    output_tokens,
                    canonical(receipt),
                    utcnow(),
                    attempt_id,
                ),
            )
            violation = known and (
                input_tokens > row["input_bound"]
                or output_tokens > row["output_bound"]
                or actual > row["reserved_micros"]
            )
            if violation:
                # Preserve actual cost rather than silently clipping to the reservation.
                conn.execute(
                    "UPDATE settings SET payload=? WHERE key='provider_dispatch_enabled'",
                    (canonical(False),),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO settings VALUES('provider_dispatch_enabled',?,1)",
                    (canonical(False),),
                )
            self.repository.event(
                conn,
                row["task_id"],
                "budget_changed",
                {
                    "attempt_id": attempt_id,
                    "state": status,
                    "actual_micros": actual,
                    "reservation_violation": bool(violation),
                },
            )
        if violation:
            raise DomainError("RESERVATION_VIOLATION", "服务用量超过已登记上界，已阻止后续调用")

    def pass_smoke(self, evidence_ref: dict):
        if not evidence_ref.get("id") or not evidence_ref.get("content_sha256"):
            raise ValueError("smoke pass requires persisted evidence")
        with self.repository.transaction() as conn:
            if not evidence_ref.get("task_id"):
                raise DomainError("SMOKE_EVIDENCE_MISSING", "协议验证必须引用已保存的完整报告")
            report = self.repository.object(
                conn,
                evidence_ref["task_id"],
                "validation",
                evidence_ref["id"],
                evidence_ref.get("version", 1),
            )
            if (
                content_hash(report) != evidence_ref["content_sha256"]
                or report.get("schema_version") != "combined-provider-protocol-validation/1"
                or report.get("passed") is not True
            ):
                raise DomainError("SMOKE_EVIDENCE_INVALID", "协议验证报告不完整或哈希不一致")
            cases = report.get("cases", [])
            if {c.get("model") for c in cases if c.get("passed") is True} != {
                "qwen3.8-flash",
                "qwen3.7-plus",
                "qwen3.8-max",
            }:
                raise DomainError("SMOKE_MODELS_INCOMPLETE", "三个已批准型号均须有通过记录")
            for case in cases:
                attempt = conn.execute(
                    "SELECT status,model,campaign_id,smoke FROM attempts WHERE attempt_id=?",
                    (case["attempt_id"],),
                ).fetchone()
                if (
                    not attempt
                    or attempt["status"] != "settled"
                    or attempt["model"] != case["model"]
                    or attempt["campaign_id"] != self.campaign_id
                    or not attempt["smoke"]
                ):
                    raise DomainError("SMOKE_ATTEMPT_INVALID", "报告引用的请求账单未核实")
            known = conn.execute(
                "SELECT count(*) FROM attempts WHERE campaign_id=? AND smoke=1 AND status='settled'",
                (self.campaign_id,),
            ).fetchone()[0]
            unknown = conn.execute(
                "SELECT count(*) FROM attempts WHERE campaign_id=? AND smoke=1 AND status IN ('reserved','dispatched','unknown')",
                (self.campaign_id,),
            ).fetchone()[0]
            if not known or unknown:
                raise DomainError("SMOKE_INCOMPLETE", "协议验证用量或结果尚未核实")
            conn.execute(
                "UPDATE campaigns SET smoke_passed=1 WHERE campaign_id=?", (self.campaign_id,)
            )
            conn.execute(
                "INSERT INTO settings VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,revision=revision+1",
                ("smoke_evidence", canonical(evidence_ref)),
            )
