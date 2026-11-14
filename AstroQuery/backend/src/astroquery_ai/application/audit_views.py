"""Exact-publication audit projections; never used for execution or exports."""
from astroquery_ai.runtime.codec import digest
from datetime import datetime
from astroquery_ai.runtime.errors import DomainError
from . import research_views
from .delivery_projections import ProjectionUnavailable


def read(service, conn, task_id, delivery_id, resource, *, revision=None, view=None,
         offset=0, limit=100, projection=None, property_id=None, source_id=None,
         action='all', activity_kind=None, activity_start=None, activity_end=None, effect='all', **options):
    kind = {('quality', None): 'quality', ('differences', None): 'difference',
            ('changes', 'activity'): 'activity', ('coverage', 'matrix'): 'matrix'}.get((resource, view))
    if kind is None:
        return None
    scope = service.display_scope(conn, task_id, delivery_id, revision, **options)
    source, cutoff = scope['source'], scope['cutoff']
    if kind == 'quality':
        header = service._projection_index.read_existing(
            (source, delivery_id, scope['revision'], scope['sha']), lambda reader: reader.get('header')) or {}
        score = header.get('task_score') or {}
        if score.get('report_id') and conn.execute(
            "SELECT 1 FROM objects WHERE task_id=? AND kind='quality' AND object_id=? "
            "AND content_sha256=? AND created_at<=? LIMIT 1",
            (source, score['report_id'], digest(score), cutoff)).fetchone():
            # The frozen header contains this exact authoritative score, not a
            # recomputation. No other audit tab or delivery body is needed.
            return {'delivery_id': delivery_id, 'delivery_revision': scope['revision'],
                    'snapshot_ref': header['snapshot_ref'], 'body': score}
    # Published measurements remain immutable. Auxiliary metadata can be repaired
    # independently; validate those identities before looking up the projection.
    dependencies = [tuple(row) for row in conn.execute(
        "SELECT kind,object_id,version,content_sha256,created_at FROM objects WHERE task_id=? AND created_at<=? "
        "AND kind IN ('quality','difference','insight','material_preparation','reading_batch_state') "
        "ORDER BY kind,object_id,version", (source, cutoff))]
    reviews = [tuple(row) for row in conn.execute(
        'SELECT review_id,payload FROM reviews WHERE task_id=? ORDER BY review_id', (source,))]
    # Review payloads can be bytes. Their exact representation is only hashed,
    # never included in public diagnostics or retained as a second cache body.
    identity = (source, delivery_id, scope['revision'], scope['sha'], 'audit/2',
                digest([dependencies, repr(reviews)]))
    body = None
    def build():
        nonlocal body
        if body is None:
            body = service.read_snapshot(conn, source, delivery_id, scope['revision'])
        if not {'measurements', 'definitions', 'provenance_bundle'} <= body.keys():
            raise ProjectionUnavailable(body)
        def report(name):
            ref = (body.get(name) or {}).get('report_ref')
            return service.repository.object(conn, source, name, ref['id'], ref['version']) if ref else None
        quality, difference = report('quality'), report('difference')
        insight = report('insight')
        if insight is None:
            insight = next(iter(research_views.historical_insights(conn, source, body, cutoff)), None)
        yield 'identity', '', {'snapshot_ref': body['snapshot_ref']}
        yield 'quality', '', {'body': quality}
        yield 'difference', '', {'body': difference}
        activity = research_views.activities(body, difference, research_views.review_details(conn, source, body))
        yield 'activity_filters', '', {'items': [
            {**{key: row.get(key) for key in ('kind','property_id','source_ids','measurement_ids','at','actual_change','status')},
             'position': str(index)} for index, row in enumerate(activity)]}
        for index, row in enumerate(activity):
            yield 'activity_row', str(index), row
        yield 'matrix', '', {'items': research_views.coverage_matrix(
            body, quality, difference, insight, research_views.process_facts(conn, source, cutoff))}
    def select(reader):
        result = {'delivery_id': delivery_id, 'delivery_revision': scope['revision'],
                  'snapshot_ref': reader.get('identity')['snapshot_ref']}
        if kind in {'quality', 'difference'}:
            payload = reader.get(kind)
            if payload['body'] is None:
                raise ProjectionUnavailable({})
            return {**result, **payload}
        start, size = max(0, offset), min(max(1, limit), 500)
        if kind == 'activity':
            category = activity_kind or action
            filtered = category not in {None,'all'} or property_id not in {None,'all'} or source_id not in {None,'all'} or activity_start or activity_end or effect != 'all'
            if filtered or projection == 'page':
                metadata = reader.get('activity_filters')['items']
                def timestamp(value):
                    try:
                        return datetime.fromisoformat(value).timestamp() if value else None
                    except (TypeError, ValueError):
                        return None
                begin, end = timestamp(activity_start), timestamp(activity_end)
                if (activity_start and begin is None) or (activity_end and end is None):
                    raise DomainError('ACTIVITY_TIME_RANGE', '处理记录的日期范围无效', 422)
                matched = [row for row in metadata if
                    (category in {None,'all'} or row['kind'] == category) and
                    (property_id in {None,'all'} or row['property_id'] == property_id) and
                    (source_id in {None,'all'} or source_id in (row['source_ids'] or [])) and
                    (begin is None or timestamp(row['at']) is not None and timestamp(row['at']) >= begin) and
                    (end is None or timestamp(row['at']) is not None and timestamp(row['at']) < end) and
                    (effect == 'all' or effect == 'changed' and row['actual_change'] or effect == 'no_change' and row['status'] == 'no_change')]
                page = reader.selected('activity_row', [row['position'] for row in matched[start:start+size]])
                return {**result, 'items': page, 'total': len(matched), 'offset': start, 'limit': size,
                        **({'matched_measurements': len({mid for row in matched for mid in row['measurement_ids'] or []})} if projection == 'page' else {})}
            return {**result, 'items': reader.rows('activity_row',offset=start,limit=size),
                    'total': reader.count('activity_row'), 'offset': start, 'limit': size}
        rows = reader.get(kind)['items']
        return {**result, 'items': rows[start:start + size], 'total': len(rows),
                'offset': start, 'limit': size}
    try:
        result = service._projection_index.read(identity, build, select)
        if kind == 'activity' and projection == 'page':
            ids = list(dict.fromkeys(mid for row in result['items'] for mid in row.get('measurement_ids', [])))
            result['records'] = service.read_material_records(conn, task_id, delivery_id, scope['revision'], ids)
        return result
    except ProjectionUnavailable:
        return None
