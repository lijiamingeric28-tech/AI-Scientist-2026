"""Stable delivery facade shared by CLI, HTTP, recovery and export."""

from threading import Lock

from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.science.results import publication as _publication, exporting as _exporting

from astroquery_ai.science.results.publication import (
    current_delivery_measurements,
    current_derived_representations,
)

from astroquery_ai.science.results.exporting import csv_display


class DeliveryService:
    def __init__(self, repository, artifacts):
        self.repository, self.artifacts = (repository, artifacts)
        self._display_lock = Lock()
        self._display_key = None
        self._display_body = None
        self._material_key = None
        self._material_index = None

    def read_snapshot(self, conn, source_task, delivery_id, revision):
        """Read-only projections share one decoded, immutable revision. Verify it still exists."""
        meta = conn.execute("SELECT content_sha256,length(payload) FROM objects WHERE task_id=? "
                            "AND kind='delivery' AND object_id=? AND version=?",
                            (source_task, delivery_id, revision)).fetchone()
        if meta is None:
            raise DomainError('OBJECT_NOT_FOUND', '所需交付修订不存在', 404)
        key = source_task, delivery_id, revision, meta[0]
        with self._display_lock:
            if key == self._display_key:
                return self._display_body
            body = self.repository.object(conn, source_task, 'delivery', delivery_id, revision)
            # Retain at most one decoded delivery, including ordinary bulk photometry.
            if meta[1] <= 128 * 1024 * 1024:
                self._display_key, self._display_body = key, body
            return body

    def read_for_display(self, conn, task_id, delivery_id=None, revision=None, *, allow_published=False):
        if allow_published and delivery_id is not None and revision is not None:
            source, _ = _publication.delivery_reference(self, conn, task_id)
            return self.read_snapshot(conn, source, delivery_id, revision)
        source, ref = _publication.delivery_reference(self, conn, task_id, delivery_id)
        if revision is not None and not 1 <= revision <= ref['version']:
            raise DomainError('DELIVERY_CHANGED', '指定历史交付修订不可用', 409)
        return self.read_snapshot(conn, source, ref['id'], ref['version'] if revision is None else revision)

    def material_index(self, conn, source_task, body, cutoff):
        from astroquery_ai.application.material_workbench import MaterialIndex
        from astroquery_ai.application.research_views import saved_before

        key = source_task, body['delivery_id'], body['revision'], body['snapshot_ref']['content_sha256']
        with self._display_lock:
            if key == self._material_key:
                return self._material_index
            preparations = saved_before(conn, source_task, 'material_preparation', cutoff)
            preparation = max(preparations, key=lambda item: item.get('revision', 0), default={})
            index = MaterialIndex(body, preparation)
            self._material_key, self._material_index = key, index
            return index

    def material_overview(self, conn, source_task, body, *, as_of=None):
        from astroquery_ai.application.material_workbench import material_overview

        if (overview := material_overview(body)) is not None:
            return overview
        row = conn.execute("SELECT created_at FROM objects WHERE task_id=? AND kind='delivery' "
                           "AND object_id=? AND version=?",
                           (source_task, body['delivery_id'], body['revision'])).fetchone()
        index = self.material_index(conn, source_task, body, row[0] if row else None)
        overview = material_overview(body, index)
        if as_of and overview["state"] == "pending":
            from astroquery_ai.science.material_summaries import summary_progress

            counts = summary_progress(conn, source_task, body, before=as_of)
            for property_coverage in overview["properties"]:
                progress = counts.get(property_coverage["property_id"], {})
                property_coverage["ready"] = min(property_coverage["total"], progress.get("ready", 0))
                property_coverage["failed"] = min(property_coverage["total"] - property_coverage["ready"],
                                                  progress.get("failed", 0))
        return overview

    preview = _publication.preview
    seal = _publication.seal
    finish_insights = _publication.finish_insights
    get = _publication.get
    delivery_reference = _publication.delivery_reference
    export = _exporting.export
    _serialize = staticmethod(_exporting._serialize)
