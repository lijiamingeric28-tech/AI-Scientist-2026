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
    def __init__(self, repository, artifacts, *, knowledge_store=None):
        self.repository, self.artifacts = (repository, artifacts)
        self.knowledge_store = knowledge_store
        self._display_lock = Lock()
        self._display_key = None
        self._display_body = None
        from astroquery_ai.runtime.result_index import ResultReadIndex
        self._read_index = ResultReadIndex(repository.path.parent / 'cache' / 'ui-read-models.sqlite3')
        from astroquery_ai.runtime.delivery_index import DeliveryProjectionIndex
        self._projection_index = DeliveryProjectionIndex(self._read_index)
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

    def _display_reference(self, conn, task_id, delivery_id, revision, *, allow_published):
        # Explicit historical coordinates may select an earlier publication;
        # unpinned reads still require the authoritative current delivery ID.
        explicit = allow_published and delivery_id is not None and revision is not None
        source, current = _publication.delivery_reference(self, conn, task_id,
            None if explicit else delivery_id)
        delivery_id = current['id'] if delivery_id is None else delivery_id
        revision = current['version'] if revision is None else revision
        if (type(revision) is not int or revision < 1 or
                delivery_id == current['id'] and revision > current['version']):
            raise DomainError('DELIVERY_CHANGED', '指定历史交付修订不可用', 409)
        if source != task_id and delivery_id != current['id']:
            # A replay owns the captured publication horizon, not future
            # deliveries subsequently produced by its still-live source task.
            row = conn.execute("SELECT created_at FROM objects WHERE task_id=? AND kind='delivery' "
                "AND object_id=? AND version=?", (source, delivery_id, revision)).fetchone()
            horizon = conn.execute("SELECT created_at FROM objects WHERE task_id=? AND kind='delivery' "
                "AND object_id=? AND version=?", (source, current['id'], current['version'])).fetchone()
            if row is None or horizon is None or row[0] > horizon[0]:
                raise DomainError('DELIVERY_CHANGED', '指定交付不属于此回放的历史范围', 409)
        return source, delivery_id, revision

    def read_for_display(self, conn, task_id, delivery_id=None, revision=None, *, allow_published=False):
        source, delivery_id, revision = self._display_reference(conn, task_id, delivery_id, revision,
                                                               allow_published=allow_published)
        return self.read_snapshot(conn, source, delivery_id, revision)

    def display_scope(self, conn, task_id, delivery_id=None, revision=None, *, expected_revision=None,
                      at_seq=None, sealed_only=False):
        """Validate publication and capture boundaries even for cache hits/304s."""
        from astroquery_ai.runtime.codec import loads
        source, delivery_id, revision = self._display_reference(conn, task_id, delivery_id, revision,
                                                               allow_published=True)
        if expected_revision is not None and revision != expected_revision:
            raise DomainError('DELIVERY_CHANGED', '交付报告已修订，请刷新后读取')
        meta = conn.execute("SELECT content_sha256,created_at FROM objects WHERE task_id=? AND kind='delivery' "
                            "AND object_id=? AND version=?", (source, delivery_id, revision)).fetchone()
        if meta is None:
            raise DomainError('OBJECT_NOT_FOUND', '所需交付修订不存在', 404)
        _, latest = self.delivery_reference(conn, task_id)
        if ((delivery_id, revision) == (latest['id'], latest['version']) and
                latest.get('content_sha256') and latest['content_sha256'] != meta[0]):
            raise DomainError('OBJECT_HASH_MISMATCH', '交付引用与保存版本不一致', 409)
        before = meta[1] if sealed_only or (delivery_id, revision) != (latest['id'], latest['version']) else None
        replay_cutoff = None
        replay_horizon = None
        if source != task_id:
            captured = self.repository.object(conn, task_id, 'replay_snapshot', task_id)
            replay_cutoff = captured.get('created_at') or meta[1]
            saved = captured.get('source_view') or {}
            replay_horizon = saved.get('core_event_cursor', saved.get('last_event_seq'))
            before = min(before, replay_cutoff) if before else replay_cutoff
        if at_seq is not None:
            frame = conn.execute('SELECT payload FROM events WHERE task_id=? AND seq=?', (source, at_seq)).fetchone()
            publication = conn.execute("SELECT payload FROM events WHERE task_id=? AND seq<=? "
                "AND json_extract(payload,'$.kind')='delivery_ready' ORDER BY seq DESC LIMIT 1", (source, at_seq)).fetchone()
            ref = loads(publication[0])['payload'].get('delivery_ref') if publication else None
            if not frame or not ref or (ref['id'], ref['version']) != (delivery_id, revision):
                raise DomainError('DELIVERY_CHANGED', '此回放时点未显示该交付', 409)
            frame_cutoff = loads(frame[0])['committed_at']
            if source != task_id and ((replay_horizon is not None and at_seq > replay_horizon) or
                    (replay_horizon is None and replay_cutoff and frame_cutoff > replay_cutoff)):
                raise DomainError('DELIVERY_CHANGED', '此时点超出回放捕获范围', 409)
            before = min(replay_cutoff, frame_cutoff) if replay_cutoff else frame_cutoff
            if sealed_only:
                before = min(before, meta[1])
        return {'source': source, 'delivery_id': delivery_id, 'revision': revision, 'sha': meta[0],
                'cutoff': meta[1], 'summary_before': before}

    def read_projection(self, conn, task_id, delivery_id, revision, select, **options):
        scope = self.display_scope(conn, task_id, delivery_id, revision, **options)
        body = None
        def build():
            nonlocal body
            from astroquery_ai.application.delivery_projections import build_projections
            if body is None:
                body = self.read_snapshot(conn, scope['source'], scope['delivery_id'], scope['revision'])
            return build_projections(self, conn, scope['source'], body, scope['cutoff'])
        identity = (scope['source'], scope['delivery_id'], scope['revision'], scope['sha'])
        return self._projection_index.read(identity, build, lambda reader: select(reader, scope))

    def read_audit_resource(self, conn, task_id, delivery_id, resource, **options):
        from astroquery_ai.application.audit_views import read
        return read(self, conn, task_id, delivery_id, resource, **options)

    def read_header(self, conn, task_id, delivery_id=None, revision=None, *, as_of=None):
        from astroquery_ai.application.delivery_projections import ProjectionUnavailable, header_projection
        def select(reader, scope):
            header = reader.get('header')
            overview = header['material_overview']
            if as_of and header['overview_dynamic'] and overview['state'] == 'pending':
                from astroquery_ai.science.material_summaries import summary_progress
                counts = summary_progress(conn, scope['source'], header, before=as_of)
                for coverage in overview['properties']:
                    progress = counts.get(coverage['property_id'], {})
                    coverage['ready'] = min(coverage['total'], progress.get('ready', 0))
                    coverage['failed'] = min(coverage['total'] - coverage['ready'], progress.get('failed', 0))
            return header
        try:
            return self.read_projection(conn, task_id, delivery_id, revision, select)
        except ProjectionUnavailable as unavailable:
            scope = self.display_scope(conn, task_id, delivery_id, revision)
            overview = self.material_overview(conn, scope['source'], unavailable.body, as_of=as_of)
            return header_projection(unavailable.body, overview)

    def read_workbench(self, conn, task_id, delivery_id, revision=None, **options):
        from astroquery_ai.application.delivery_projections import ProjectionUnavailable, restore_material_index
        try:
            return self.read_projection(conn, task_id, delivery_id, revision,
                lambda reader, scope: (reader.get('header'), restore_material_index(reader), scope), **options)
        except ProjectionUnavailable as unavailable:
            scope = self.display_scope(conn, task_id, delivery_id, revision, **options)
            return unavailable.body, self.material_index(conn, scope['source'], unavailable.body, scope['cutoff']), scope

    def read_material_summary(self, conn, task_id, delivery_id, material_id, property_id, revision=None, **options):
        from astroquery_ai.application.delivery_projections import ProjectionUnavailable, resolve_summary
        from astroquery_ai.science.material_summaries import read_summary
        def select(reader, scope):
            header = reader.get('header')
            group, pid = resolve_summary(reader, material_id, property_id)
            summary = read_summary(self.repository, conn, scope['source'], header, group, pid,
                                   before=scope['summary_before'])
            return {'delivery_id': delivery_id, 'delivery_revision': scope['revision'],
                    'snapshot_ref': header['snapshot_ref'], 'summary': summary}, scope
        try:
            return self.read_projection(conn, task_id, delivery_id, revision, select, **options)
        except ProjectionUnavailable as unavailable:
            scope = self.display_scope(conn, task_id, delivery_id, revision, **options)
            body = unavailable.body
            index = self.material_index(conn, scope['source'], body, scope['cutoff'])
            group, pid = index.resolve(material_id, property_id)
            summary = read_summary(self.repository, conn, scope['source'], body, group, pid,
                                   before=scope['summary_before'])
            return {'delivery_id': delivery_id, 'delivery_revision': scope['revision'],
                    'snapshot_ref': body['snapshot_ref'], 'summary': summary}, scope

    def read_material_records(self, conn, task_id, delivery_id, revision, ids):
        from astroquery_ai.application.delivery_projections import ProjectionUnavailable
        try:
            return self.read_projection(conn, task_id, delivery_id, revision,
                lambda reader, scope: reader.selected('list', ids))
        except ProjectionUnavailable as unavailable:
            scope = self.display_scope(conn, task_id, delivery_id, revision)
            from astroquery_ai.application.result_views import record_list
            body = unavailable.body
            reference = (body.get('quality') or {}).get('report_ref')
            quality = self.repository.object(conn, scope['source'], 'quality', reference['id'], reference['version']) if reference else None
            return record_list(body, measurement_ids=set(ids), quality=quality)

    def read_detail_resource(self, conn, task_id, delivery_id, resource, *, revision=None,
                             expected_revision=None, identifier=None, offset=0, limit=100, view=None,
                             at_seq=None, sealed_only=False):
        if resource not in {'records', 'sources', 'figures'}:
            return None
        start, size = max(0, offset), min(max(1, limit), 500)
        kind = {'records': 'detail', 'sources': 'source', 'figures': 'figure'}[resource]
        def select(reader, scope):
            header = reader.get('header')
            if resource == 'records' and reader.count(kind) != header['display_counts']['records']:
                return None  # Preserve historical incomplete detail behavior.
            if identifier is not None:
                item = reader.get(kind, identifier)
                if item is None:
                    code, label = {'records': ('RECORD', '记录'), 'sources': ('SOURCE', '来源'), 'figures': ('FIGURE', '图像')}[resource]
                    raise DomainError(code + '_NOT_FOUND', '当前交付修订没有此' + label, 404)
                total, rows = 1, [item][start:start+size]
            else:
                total, rows = reader.count(kind), reader.rows(kind, offset=start, limit=size)
            if resource == 'records':
                from astroquery_ai.science.evidence_views import focus_record_views
                for item in rows:
                    activity = item.pop('_activity')
                    receipt = item.pop('_processing_receipt')
                    source = item.pop('_source_metadata')
                    answers = item.pop('_review_answers')
                    if view == 'summary':
                        binding = item['property_binding']
                        item['property_binding'] = {'property_id': binding['property_id'],
                            'definition': {'name_cn': binding['definition']['name_cn']},
                            'output_profile': {k: binding['output_profile'][k] for k in ('unit', 'representation')}}
                        for name in ('evidence', 'evidence_views', 'source_statements', 'reported_references', 'interpretation'):
                            item.pop(name, None)
                        item['details_loaded'] = False
                    elif identifier is not None:
                        from astroquery_ai.application.research_views import review_details
                        questions = review_details(conn, scope['source'], {'provenance_bundle': {'human_answers': answers}})
                        for step in activity:
                            if step['kind'] == 'human':
                                step['question'] = questions.get(step['id'])
                        item['activity'], item['processing_receipt'] = activity, receipt
                        item['evidence_views'] = focus_record_views(conn, scope['source'], scope['cutoff'], source,
                                                                    item['source'], item['evidence_views'])
            elif resource == 'figures':
                from astroquery_ai.application.material_workbench import figure_view
                rows = [figure_view(task_id, row) for row in rows]
            return {'delivery_id': scope['delivery_id'], 'delivery_revision': scope['revision'],
                    'snapshot_ref': header['snapshot_ref'], 'items': rows, 'total': total, 'offset': start, 'limit': size,
                    **({'coverage': reader.get('figure_coverage')['items']} if resource == 'figures' else {})}
        from astroquery_ai.application.delivery_projections import ProjectionUnavailable
        try:
            return self.read_projection(conn, task_id, delivery_id, revision, select, expected_revision=expected_revision,
                                        at_seq=at_seq, sealed_only=sealed_only)
        except ProjectionUnavailable:
            return None  # Existing per-resource route owns older partial bodies.

    def read_page(self, conn, task_id, delivery_id, resource, *, revision=None,
                  expected_revision=None, filters=None, offset=0, limit=100,
                  collapse_duplicates=False, ids_only=False, projection='list', at_seq=None, sealed_only=False):
        """Validate the authoritative reference before touching a derived index."""
        scope = self.display_scope(conn, task_id, delivery_id, revision, expected_revision=expected_revision,
                                   at_seq=at_seq, sealed_only=sealed_only)
        source, delivery_id, revision = scope['source'], scope['delivery_id'], scope['revision']
        if expected_revision is not None and revision != expected_revision:
            raise DomainError('DELIVERY_CHANGED', '交付报告已修订，请刷新后读取')
        meta = conn.execute("SELECT content_sha256 FROM objects WHERE task_id=? AND kind='delivery' "
                            "AND object_id=? AND version=?", (source, delivery_id, revision)).fetchone()
        if meta is None:
            raise DomainError('OBJECT_NOT_FOUND', '所需交付修订不存在', 404)
        if resource not in {'records', 'sources'}:
            raise DomainError('RESOURCE_NOT_FOUND', '没有此资源的列表投影', 404)
        if projection not in {'list', 'analysis'} or projection == 'analysis' and resource != 'records':
            raise DomainError('INVALID_RESULT_PROJECTION', '没有此资源的分析投影', 422)

        def build():
            from astroquery_ai.application.delivery_projections import ProjectionUnavailable
            def select(reader, _scope):
                labels = reader.rows('source_list')
                rows = reader.rows(projection if resource == 'records' else 'source_list')
                return rows, {'resource': resource, 'delivery_id': delivery_id, 'delivery_revision': revision,
                    'snapshot_ref': reader.get('header')['snapshot_ref'], 'source_labels': {s['source_id']: s for s in labels}}
            try:
                return self.read_projection(conn, task_id, delivery_id, revision, select,
                                            at_seq=at_seq, sealed_only=sealed_only)
            except ProjectionUnavailable as unavailable:
                from astroquery_ai.application.result_views import analysis_list, record_list, source_list
                body = unavailable.body
                labels = source_list(body)
                quality_ref = (body.get('quality') or {}).get('report_ref')
                quality = self.repository.object(conn, source, 'quality', quality_ref['id'], quality_ref['version']) if resource == 'records' and quality_ref else None
                if projection == 'analysis':
                    reference = (body.get('difference') or {}).get('report_ref')
                    report = self.repository.object(conn, source, 'difference', reference['id'], reference['version']) if reference else None
                    rows = analysis_list(body, quality, report)
                else:
                    rows = record_list(body, quality=quality) if resource == 'records' else labels
                return rows, {'resource': resource, 'delivery_id': delivery_id, 'delivery_revision': revision,
                    'snapshot_ref': body['snapshot_ref'], 'source_labels': {s['source_id']: s for s in labels}}

        return self._read_index.read((source, delivery_id, revision, meta[0], resource, projection), build,
            filters=filters, offset=offset, limit=limit, collapse_duplicates=collapse_duplicates, ids_only=ids_only)

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
