"Atomic job/producers operations on the owning Repository connection."

from __future__ import annotations

from astroquery_ai.runtime.codec import canonical, digest, loads, new_id, utcnow

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.runtime.models import TERMINAL


def enqueue(
    self,
    conn,
    task_id: str,
    owner: str,
    kind: str,
    payload: dict,
    dependencies: list[str] | None = None,
) -> str:
    task = self.task(conn, task_id)
    if task["lifecycle"] in TERMINAL or task["kind"] != "live":
        raise DomainError("TASK_READ_ONLY", "该任务不能执行作业")
    key = digest({"owner": owner, "kind": kind, "payload": payload})
    old = conn.execute(
        "SELECT job_id FROM jobs WHERE task_id=? AND logical_key=?", (task_id, key)
    ).fetchone()
    if old:
        return old[0]
    job_id = new_id()
    conn.execute(
        "INSERT INTO jobs(job_id,task_id,logical_key,owner,kind,payload,status,generation,created_at) VALUES(?,?,?,?,?,?,'ready',?,?)",
        (job_id, task_id, key, owner, kind, canonical(payload), task["generation"], utcnow()),
    )
    for dep in dependencies or []:
        parent = conn.execute("SELECT task_id FROM jobs WHERE job_id=?", (dep,)).fetchone()
        if parent is None or parent[0] != task_id:
            raise DomainError("INVALID_DEPENDENCY", "作业依赖不属于该任务", 422)
        conn.execute(
            "INSERT INTO job_dependencies(job_id,dependency_id) VALUES(?,?)", (job_id, dep)
        )
    from astroquery_ai.runtime.stages import STAGES, JOB_STAGE, current_stage, set_stage

    checkpoint, stage = (current_stage(conn, task_id), JOB_STAGE.get(kind))
    if (
        checkpoint
        and stage
        and (STAGES.index(stage) < STAGES.index(checkpoint["stage_id"]))
        and (
            not conn.execute(
                "SELECT 1 FROM jobs WHERE task_id=? AND status='running' LIMIT 1", (task_id,)
            ).fetchone()
        )
    ):
        set_stage(self, conn, task_id, stage, repair=True)
    return job_id


def close_failed_metadata_dependencies(self, conn, task_id, reason):
    """Keep each edge and its failure receipt; only release the M04 checkpoint wait."""
    rows = conn.execute(
        "SELECT d.job_id,d.dependency_id,p.status FROM job_dependencies d JOIN jobs j ON j.job_id=d.job_id JOIN jobs p ON p.job_id=d.dependency_id WHERE j.task_id=? AND j.kind='literature_discover' AND p.owner='M03' AND p.kind='catalog_discover' AND p.status IN ('failed','not_run','cancelled') AND d.resolution='required'",
        (task_id,),
    ).fetchall()
    for row in rows:
        receipt = {
            "job_id": row["job_id"],
            "dependency_id": row["dependency_id"],
            "dependency_status": row["status"],
            "reason": reason,
            "resolution": "closed_without_result",
            "scientific_read_granted": False,
        }
        reference = self.put_object(
            conn, task_id, "dependency_resolution", "dependency-" + digest(receipt), 1, receipt
        )
        conn.execute(
            "UPDATE job_dependencies SET resolution='closed_without_result',resolution_ref=? WHERE job_id=? AND dependency_id=?",
            (canonical(reference).decode(), row["job_id"], row["dependency_id"]),
        )
        self.event(conn, task_id, "dependency_closed", {"resolution_ref": reference})


def dispatch_delay(self, default=1.0):
    import time

    now = time.time()
    with self.read() as conn:
        row = conn.execute(
            "SELECT min(json_extract(CAST(w.payload AS TEXT),'$.eligible_at'))\n                FROM objects w JOIN jobs j ON j.job_id=w.object_id AND j.task_id=w.task_id\n                JOIN tasks t ON t.task_id=j.task_id\n                WHERE w.kind='dispatch_wait' AND j.status='ready'\n                AND t.lifecycle IN ('clarifying','queued','running') AND t.resume_required=0\n                AND w.version=(SELECT max(w2.version) FROM objects w2 WHERE w2.task_id=w.task_id\n                    AND w2.kind=w.kind AND w2.object_id=w.object_id)\n                AND json_extract(CAST(w.payload AS TEXT),'$.eligible_at')>?",
            (now,),
        ).fetchone()
    return max(0.01, min(default, row[0] - now)) if row[0] else default


def claim_job(self, owner_id: str, lease_seconds=60, *, task_id=None, material_scope=None) -> dict | None:
    import time
    from astroquery_ai.runtime.stages import EXECUTION_POLICY, current_stage, eligible, record_locks

    with self.transaction() as conn:
        running = [dict(r) for r in conn.execute("SELECT * FROM jobs WHERE status='running'")]
        for running_job in running:
            running_job["payload"] = loads(running_job["payload"])
            running_job["record_locks"] = record_locks(self, conn, running_job)
        # Normal queries remain mutually exclusive. A module experiment may
        # opt in only when both sides have the same hash-valid material scope.
        material_scope = material_scope or getattr(self, 'material_experiment_scope', None)
        def same_material_scope(tid):
            if material_scope != 'literature-lab/1':return False
            task=self.task(conn,tid)
            if task['kind']!='live' or not task['query_ref']:return False
            ref=loads(task['query_ref'])
            spec=self.object(conn,tid,'confirmed_query',ref['id'],ref['version'])
            return (spec.get('module_experiment',{}).get('version')==material_scope
                    and spec.get('run_policy',{}).get('literature',{}).get('stop_after_materials') is True
                    and spec.get('spec_hash')==digest({k:v for k,v in spec.items() if k!='spec_hash'}))
        parallel_materials=bool(task_id and same_material_scope(task_id)
                                and all(same_material_scope(j['task_id']) for j in running))
        if len(running) >= EXECUTION_POLICY["workers"]:
            return None
        candidates = conn.execute(
            "SELECT j.* FROM jobs j JOIN tasks t USING(task_id)\n                WHERE j.status='ready' AND t.lifecycle IN ('clarifying','queued','running')\n                AND (? IS NULL OR j.task_id=?)\n                AND j.generation=t.generation AND t.resume_required=0\n                AND NOT EXISTS(SELECT 1 FROM objects w WHERE w.task_id=j.task_id AND w.kind='dispatch_wait'\n                  AND w.object_id=j.job_id AND w.version=(SELECT max(w2.version) FROM objects w2\n                    WHERE w2.task_id=j.task_id AND w2.kind='dispatch_wait' AND w2.object_id=j.job_id)\n                  AND json_extract(CAST(w.payload AS TEXT),'$.eligible_at')>?)\n                AND (j.kind<>'finalize' OR NOT EXISTS(\n                  SELECT 1 FROM jobs a WHERE a.task_id=j.task_id AND a.kind<>'finalize'\n                  AND a.status IN ('ready','running','waiting_dependency','awaiting_review')))\n                AND (? OR NOT EXISTS(SELECT 1 FROM jobs a WHERE a.status='running' AND a.task_id<>j.task_id))\n                AND NOT EXISTS(SELECT 1 FROM job_dependencies d JOIN jobs p ON p.job_id=d.dependency_id WHERE d.job_id=j.job_id AND d.resolution='required' AND p.status<>'succeeded')\n                ORDER BY coalesce((SELECT max(d.turn) FROM dispatch_turns d WHERE d.task_id=j.task_id),0),\n                  CASE WHEN j.owner='review' THEN 0 ELSE 1 END,\n                  coalesce((SELECT d.turn FROM dispatch_turns d WHERE d.task_id=j.task_id AND d.owner=j.owner),0),j.created_at,j.rowid",
            (task_id, task_id, time.time(), int(parallel_materials)),
        ).fetchall()
        row = None
        for candidate in candidates:
            job = dict(candidate)
            job["payload"] = loads(job["payload"])
            checkpoint = current_stage(conn, job["task_id"])
            if checkpoint:
                job["record_locks"] = record_locks(self, conn, job)
                if not eligible(job, running, checkpoint):
                    continue
            elif len(running) >= 2 or any(
                (
                    a["owner"] == job["owner"]
                    and (
                        job["owner"] != "M06"
                        or a["payload"].get("work_id") == job["payload"].get("work_id")
                    )
                    for a in running
                )
            ):
                continue
            row = candidate
            break
        if row is None:
            return None
        lease = new_id()
        turn = conn.execute("SELECT coalesce(max(turn),0)+1 FROM dispatch_turns").fetchone()[0]
        conn.execute(
            "INSERT INTO dispatch_turns VALUES(?,?,?) ON CONFLICT(task_id,owner) DO UPDATE SET turn=excluded.turn",
            (row["task_id"], row["owner"], turn),
        )
        conn.execute(
            "UPDATE jobs SET status='running',lease_token=?,lease_owner=?,lease_until=?,attempt_count=attempt_count+1 WHERE job_id=?",
            (lease, owner_id, time.time() + lease_seconds, row["job_id"]),
        )
        task = self.task(conn, row["task_id"])
        if task["lifecycle"] == "queued":
            self.mutate_task(conn, task["task_id"], lifecycle="running")
        self.event(
            conn,
            row["task_id"],
            "job_state_changed",
            {"job_id": row["job_id"], "owner": row["owner"], "status": "running"},
        )
        result = dict(
            conn.execute("SELECT * FROM jobs WHERE job_id=?", (row["job_id"],)).fetchone()
        )
        result["payload"] = loads(result["payload"])
        return result


def validate_lease(self, conn, job: dict, *, scientific=True):
    import time

    task = self.task(conn, job["task_id"])
    row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job["job_id"],)).fetchone()
    if (
        row is None
        or row["status"] != "running"
        or row["lease_token"] != job["lease_token"]
        or (row["lease_until"] < time.time())
    ):
        raise DomainError("LEASE_EXPIRED", "作业提交资格已过期")
    if task["generation"] != job["generation"] or task["lifecycle"] in TERMINAL | {"cancelling"}:
        raise DomainError("STALE_GENERATION", "任务代次已变化")
    if scientific and task["science_state"] == "sealed":
        raise DomainError("SCIENCE_SEALED", "科学结果已封口")
    if scientific:
        self.guard_definitions(conn, task)
        from astroquery_ai.runtime.run_policy import guard
        guard(self, conn, job)
    return task


def guard_definitions(self, conn, task: dict):
    if not task["query_ref"]:
        return
    spec_ref = loads(task["query_ref"])
    spec = self.object(
        conn, task["task_id"], "confirmed_query", spec_ref["id"], spec_ref["version"]
    )
    deps = {ref["id"] for ref in spec["dependencies"]}
    for event in conn.execute(
        "SELECT dependency_id,reason FROM revocations WHERE release_id=?",
        (spec["registry_release"]["id"],),
    ):
        if event["dependency_id"] is None or event["dependency_id"] in deps:
            raise DomainError(
                "DEFINITION_INVALIDATED", "冻结请求依赖的科学定义已失效", reason=event["reason"]
            )


def renew(self, job: dict, lease_seconds=60):
    import time

    with self.transaction() as conn:
        row = conn.execute(
            "SELECT status,generation,attempt_count FROM jobs WHERE job_id=?", (job["job_id"],)
        ).fetchone()
        if (
            row
            and row["status"] == "succeeded"
            and (row["generation"] == job["generation"])
            and (row["attempt_count"] == job["attempt_count"])
        ):
            return False
        self.validate_lease(conn, job, scientific=False)
        conn.execute(
            "UPDATE jobs SET lease_until=? WHERE job_id=?",
            (time.time() + lease_seconds, job["job_id"]),
        )
        return True


def finish_job(self, conn, job: dict, result_ref: dict | None = None):
    self.validate_lease(conn, job, scientific=False)
    conn.execute(
        "UPDATE jobs SET status='succeeded',result_ref=?,lease_token=NULL,lease_until=NULL WHERE job_id=?",
        (canonical(result_ref).decode() if result_ref else None, job["job_id"]),
    )
    self.event(
        conn, job["task_id"], "job_state_changed", {"job_id": job["job_id"], "status": "succeeded"}
    )
    task = self.task(conn, job["task_id"])
    if task["lifecycle"] == "pausing" and (
        not conn.execute(
            "SELECT 1 FROM jobs WHERE task_id=? AND status='running'", (job["task_id"],)
        ).fetchone()
    ):
        self.mutate_task(conn, task["task_id"], lifecycle="paused")
        self.event(conn, task["task_id"], "task_state_changed", {"lifecycle": "paused"})


def producer(self, conn, task_id: str, producer_id: str, *, close_reason=None, watermark=0):
    old = conn.execute(
        "SELECT * FROM producers WHERE task_id=? AND producer_id=?", (task_id, producer_id)
    ).fetchone()
    if old and old["state"] == "closed":
        if watermark > old["watermark"] or close_reason != old["close_reason"]:
            raise DomainError("PRODUCER_CLOSED", "生产者已经关闭")
        return
    if old and watermark < old["watermark"]:
        raise DomainError("WATERMARK_REGRESSION", "生产进度不能回退")
    state = "closed" if close_reason else "open"
    conn.execute(
        "INSERT INTO producers VALUES(?,?,1,?,?,?) ON CONFLICT(task_id,producer_id) DO UPDATE SET revision=revision+1,state=excluded.state,watermark=excluded.watermark,close_reason=excluded.close_reason",
        (task_id, producer_id, state, watermark, close_reason),
    )
    if close_reason:
        self.event(
            conn,
            task_id,
            "producer_closed",
            {"producer_id": producer_id, "reason": close_reason, "watermark": watermark},
        )
