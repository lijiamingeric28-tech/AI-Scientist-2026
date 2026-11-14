"""Existing retired HTTP routes; business services retain authority."""

from __future__ import annotations

from astroquery_ai.runtime.errors import DomainError


def register(app, application, scheduler):

    @app.delete("/api/tasks/{task_id}/records/{record_id}")
    def removed_record_mutation(task_id: str, record_id: str):
        raise DomainError(
            "RECORD_MUTATION_REMOVED", "任务保留全部合格测量；筛选和勾选仅影响本次导出", 410
        )

    @app.post("/api/upload")
    def removed_upload():
        raise DomainError("MANUAL_PDF_REMOVED", "本版使用经过来源核验的论文获取流程", 410)
