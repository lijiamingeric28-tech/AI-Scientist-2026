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
            if meta[1] <= 64 * 1024 * 1024:
                self._display_key, self._display_body = key, body
            return body

    def read_for_display(self, conn, task_id, delivery_id=None, revision=None):
        source, ref = _publication.delivery_reference(self, conn, task_id, delivery_id)
        if revision is not None and not 1 <= revision <= ref['version']:
            raise DomainError('DELIVERY_CHANGED', '指定历史交付修订不可用', 409)
        return self.read_snapshot(conn, source, ref['id'], ref['version'] if revision is None else revision)

    preview = _publication.preview
    seal = _publication.seal
    finish_insights = _publication.finish_insights
    get = _publication.get
    export = _exporting.export
    _serialize = staticmethod(_exporting._serialize)
