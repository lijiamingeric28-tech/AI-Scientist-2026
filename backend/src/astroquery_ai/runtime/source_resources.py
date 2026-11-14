"""One repository ledger for network bytes plus local container expansion."""

from .codec import new_id, utcnow
from .errors import DomainError


def local_source_bytes(repository, conn, task_id):
    return sum(
        item["actual_bytes"] if item["state"] == "settled" else item["byte_bound"]
        for item in repository.objects(conn, task_id, "source_resource")
        if item["kind"] == "container_expansion"
    )


class SourceResources:
    def __init__(self, repository):
        self.repository = repository

    def reserve_container(self, job, artifact):
        tid = job["task_id"]
        bound = 32 * 1024**2
        with self.repository.transaction() as conn:
            self.repository.validate_lease(conn, job)
            local = local_source_bytes(self.repository, conn, tid)
            accounting = "CASE WHEN status IN ('dispatched','unknown') THEN max(byte_bound,byte_count) ELSE byte_count END"
            total, module = conn.execute(
                f"SELECT coalesce(sum({accounting}),0),coalesce(sum(CASE WHEN owner='M05' THEN {accounting} ELSE 0 END),0) FROM http_attempts WHERE task_id=?",
                (tid,),
            ).fetchone()
            if module + local + bound > 2 * 1024**3 or total + local + bound > 3 * 1024**3:
                raise DomainError(
                    "MODULE_HTTP_BYTE_LIMIT", "容器展开与正文/附件读取共享的累计字节预算不足"
                )
            rid = new_id()
            record = {
                "resource_id": rid,
                "kind": "container_expansion",
                "owner": "M05",
                "job_id": job["job_id"],
                "artifact_ref": artifact["artifact_id"],
                "state": "reserved",
                "byte_bound": bound,
                "actual_bytes": None,
                "created_at": utcnow(),
            }
            self.repository.put_object(conn, tid, "source_resource", rid, 1, record)
            return record

    def settle(self, task_id, reservation, actual_bytes):
        if type(actual_bytes) is not int or not 0 <= actual_bytes <= reservation["byte_bound"]:
            raise DomainError("CONTAINER_RESOURCE_BOUND", "容器展开未给出有效的实际字节记录")
        with self.repository.transaction() as conn:
            current = self.repository.object(
                conn, task_id, "source_resource", reservation["resource_id"]
            )
            if current["state"] == "settled":
                if current["actual_bytes"] != actual_bytes:
                    raise DomainError(
                        "RESOURCE_SETTLEMENT_CONFLICT", "同一次展开不能重复结算不同字节数"
                    )
                return
            self.repository.put_object(
                conn,
                task_id,
                "source_resource",
                reservation["resource_id"],
                2,
                {
                    **current,
                    "state": "settled",
                    "actual_bytes": actual_bytes,
                    "settled_at": utcnow(),
                },
            )
