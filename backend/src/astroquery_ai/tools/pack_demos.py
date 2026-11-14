"""Build one portable read-only history per catalogue entry from an existing local runtime."""
import argparse
import base64
import collections
import lzma
import re
import hashlib
import json
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

from astroquery_ai.runtime.codec import canonical, content_hash


# Public history projections. Full text, parser indexes, model conversations, caches,
# credentials, requests, leases and billing are deliberately outside the archive.
OBJECTS = set("""
acquisition_result admission admission_disposition archive_comparison bibliography_choice candidate
candidate_snapshot catalog_checkpoint catalog_column_plan catalog_document catalog_identity_interpretation
catalog_identity_query catalog_pool catalog_response catalog_response_reuse catalog_screening change_event
citation_lookup cited_work comparison_input_plan comparison_plan completion_scope confirmed_query context
coverage delivery delivery_serialization_check derived derived_current difference evidence evidence_page_preview
execution_policy figure figure_coverage interpretation literature_assessment literature_candidate_evaluation
literature_feedback_state literature_item_evaluation literature_layer literature_name_plan literature_search_plan
literature_term_plan material_aliases material_compatibility material_preparation material_summary measurement message
object_match prepared_source processing_receipt property_insight_checkpoint property_insight_plan
qualification quality quality_batch_receipt quality_candidate_link quality_candidate_root quality_decision
quality_input_plan quality_plan quality_reextraction_action quality_reextraction_result read_ledger
reading_allocation reading_batch_state reading_context_note reading_figure_hint reported_source_ref request_parse
request_resolution review_answer review_application science_condition_check science_snapshot source source_check
source_statement stage_checkpoint target_astrometry uncertainty unit validation_receipt work draft insight material_analysis
""".split())


def public_pdf_url(value):
    try:
        url = urlsplit(value or '')
        if url.scheme == 'https' and url.hostname and not url.username and not url.password and not url.query and not url.fragment and url.port in (None, 443):
            return url.geturl()
    except ValueError:
        pass
    return None


def pdf_urls(db, task):
    urls = collections.defaultdict(list)
    for row in db.execute("SELECT payload FROM objects WHERE task_id=? AND kind='acquisition_result'", (task,)):
        for item in json.loads(row[0]).get('version_attempts', []):
            sha = item.get('artifact_id')
            for value in [item.get('url'), (item.get('retrieval') or {}).get('endpoint')]:
                url = public_pdf_url(value)
                if sha and url and url not in urls[sha]:
                    urls[sha].append(url)
    return urls


def work_pdf_urls(record):
    """ADS can store an arXiv id alone or as [identifier, version]."""
    for arxiv in record.get('arxivs', []):
        identifier, version = (arxiv + [None])[:2] if isinstance(arxiv, list) and arxiv else (arxiv, None)
        if not isinstance(identifier, str):
            continue
        identifier = identifier.removeprefix('arXiv:')
        if not re.fullmatch(r'(?:[0-9]{4}\.[0-9]{4,5}|[A-Za-z.-]+/[0-9]{7})(?:v[0-9]+)?', identifier):
            continue
        base = 'https://arxiv.org/pdf/' + identifier
        if version and re.fullmatch(r'v?[0-9]+', str(version)) and not re.search(r'v[0-9]+$', identifier):
            yield base + 'v' + str(version).removeprefix('v')
        yield base
    for raw in (record.get('raw') or {}).get('links_data', []):
        try:
            link = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            continue
        if isinstance(link, dict) and link.get('type') == 'pdf' and link.get('access') == 'open':
            url = public_pdf_url(link.get('url'))
            if url:
                yield url
    if record.get('bibcode'):
        from urllib.parse import quote
        yield 'https://articles.adsabs.harvard.edu/pdf/' + quote(record['bibcode'], safe='.')


def public_analysis_run(db, data, task):
    state = json.loads(data['payload'])
    if data['status'] not in {'complete', 'partial', 'failed', 'cancelled', 'interrupted'} or not state.get('reports'):
        return None
    if state['scope']['task_id'] != task:
        raise ValueError('Supplement does not belong to the selected sample')
    for ref in state['reports']:
        saved = db.execute("SELECT content_sha256,payload FROM objects WHERE task_id=? AND kind='material_analysis' AND object_id=? AND version=?",
            (task, ref['id'], ref['version'])).fetchone()
        if saved is None or saved['content_sha256'] != ref['content_sha256'] or content_hash(json.loads(saved['payload'])) != ref['content_sha256']:
            raise ValueError('Supplement report hash mismatch')
    # Public reading index only. Internal checkpoints, model permits,
    # authorization state and idempotency operations never ship.
    public = {key: state[key] for key in ('scope','reports','stage','reason','message','completed_records','total_records') if key in state}
    data['payload'] = canonical(public).decode('utf-8')
    return data


def build(db, sample, output, urls, artifact_root):
    task = sample['task_id']
    target = output / (task + '.jsonl.xz')
    objects = 'SELECT * FROM objects WHERE task_id=? ORDER BY kind,object_id,version'
    materials = {}
    recipes = {}
    for row in db.execute("SELECT payload FROM objects WHERE task_id=? AND kind='source'", (task,)):
        source = json.loads(row[0])
        if source['kind'] == 'paper' and source.get('artifact'):
            sha = source['artifact']['sha256']
            records = source['work']['records']
            links = list(urls.get(sha, []))
            for record in records:
                for url in work_pdf_urls(record):
                    if url not in links:
                        links.append(url)
            materials[sha] = {'urls': links}
    for row in db.execute("""SELECT DISTINCT a.* FROM artifacts a JOIN artifact_refs r USING(artifact_id)
            WHERE r.task_id=? AND a.media_type='application/x-votable+xml' AND a.byte_size <= 5242880""", (task,)):
        path = artifact_root / row['relative_path']
        if path.is_file():
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != row['sha256']:
                raise ValueError('Archived table bytes do not match the saved source')
            materials[row['artifact_id']] = {'table': True}
    for row in db.execute("SELECT payload FROM objects WHERE task_id=? AND kind='parser_cache'", (task,)):
        item = json.loads(row[0])
        if item.get('operation') in ('page_image', 'figure_crop') and item['source_artifact_id'] in materials:
            recipes[item['artifact']['sha256']] = {'parent': item['source_artifact_id'], 'operation': item['operation'], 'options': item['options']}
    media = {**materials, **recipes}
    def items(table, query, params):
        for row in db.execute(query, params):
            if table == 'objects' and row['kind'] not in OBJECTS:
                continue
            if table in ('artifacts','artifact_refs') and row['artifact_id'] not in media:
                continue
            data = {k: (v.decode('utf-8') if isinstance(v,bytes) else v) for k,v in dict(row).items()}
            if table == 'material_analysis_runs':
                data = public_analysis_run(db, data, task)
                if data is None:
                    continue
            if table == 'objects' and row['kind'] == 'acquisition_result':
                payload = json.loads(data['payload'])
                changed = False
                for attempt in payload.get('version_attempts', []):
                    retrieval = attempt.get('retrieval') or {}
                    if 'source_data_root' in retrieval:
                        del retrieval['source_data_root']
                        changed = True
                if changed:
                    sha = content_hash(payload)
                    if 'content_sha256' in payload:
                        payload['content_sha256'] = sha
                    data.update(payload=canonical(payload).decode('utf-8'), content_sha256=sha)
            if table == 'events':
                event = json.loads(data['payload'])
                if event['kind'] == 'budget_changed':
                    event['payload'] = {key: event['payload'][key] for key in ('attempt_id', 'state')
                                        if key in event['payload']}
                    data['payload'] = canonical(event).decode('utf-8')
            if table == 'jobs':
                for key in ('lease_token', 'lease_owner', 'lease_until'):
                    data[key] = None
            yield [table, data]

    with lzma.open(target, 'wb', preset=3) as stream:
        def write(entry):
            stream.write((json.dumps(entry,ensure_ascii=False,separators=(',',':'))+'\n').encode())
        record = db.execute('SELECT * FROM tasks WHERE task_id=?', (task,)).fetchone()
        ref = json.loads(record['delivery_ref'])
        if record['lifecycle'] != 'completed' or (ref['id'],ref['version']) != (sample['delivery_id'], sample['delivery_revision']):
            raise ValueError('The demo must match a completed, explicitly selected delivery')
        final = json.loads(db.execute("SELECT payload FROM objects WHERE task_id=? AND kind='delivery' AND object_id=? AND version=?", (task,ref['id'],ref['version'])).fetchone()[0])
        if final['snapshot_ref'] != sample['snapshot_ref']:
            raise ValueError('The selected snapshot has changed')
        write(['header', {'format':'published-history/1','task_id':task,'snapshot_ref':sample['snapshot_ref']}])
        for table, sql in [('tasks','SELECT * FROM tasks WHERE task_id=?'),
                           ('events','SELECT * FROM events WHERE task_id=? ORDER BY seq'),
                           ('jobs','SELECT * FROM jobs WHERE task_id=?'),
                           ('job_dependencies','SELECT d.* FROM job_dependencies d JOIN jobs j ON j.job_id=d.job_id WHERE j.task_id=?'),
                           ('producers','SELECT * FROM producers WHERE task_id=?'),('reviews','SELECT * FROM reviews WHERE task_id=?'),
                           ('http_attempts','SELECT * FROM http_attempts WHERE task_id=?'),('objects',objects),
                           ('artifacts','SELECT a.* FROM artifacts a WHERE EXISTS (SELECT 1 FROM artifact_refs r WHERE r.artifact_id=a.artifact_id AND r.task_id=?)'),
                           ('artifact_refs','SELECT * FROM artifact_refs WHERE task_id=?'),
                           *([('material_analysis_runs','SELECT * FROM material_analysis_runs WHERE task_id=? ORDER BY created_at,run_id')]
                             if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='material_analysis_runs'").fetchone() else [])]:
            for entry in items(table, sql, (task,)):
                write(entry)
                if table == 'artifacts' and media[entry[1]['artifact_id']].get('table'):
                    path = artifact_root / entry[1]['relative_path']
                    write(['table_bytes', {'id':entry[1]['artifact_id'],'data':base64.b64encode(path.read_bytes()).decode('ascii')}])
    with target.open('rb') as data:
        pin = hashlib.file_digest(data,'sha256').hexdigest()
    return {'sha256':pin,'snapshot_ref':sample['snapshot_ref'],'media':media}


def append_supplements(db, sample, source, entry, output):
    """Retain an installed archive and its media recipes; replace supplements only.

    Imported histories deliberately omit parser caches. Rebuilding their media
    recipes from that DB would lose PDF page/crop references, so original lines
    remain byte-for-byte and only public supplementary objects are appended.
    """
    source, output = Path(source), Path(output)
    task = sample['task_id']
    target = output / (task + '.jsonl.xz')
    if source.resolve() == target.resolve():
        raise ValueError('Build the update separately before atomic publication')
    with source.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
            raise ValueError('Original sample archive hash mismatch')
    saved = json.loads(db.execute('SELECT delivery_ref FROM tasks WHERE task_id=?', (task,)).fetchone()[0])
    if (saved['id'], saved['version']) != (sample['delivery_id'], sample['delivery_revision']):
        raise ValueError('Sample delivery revision changed')
    runs, refs = [], set()
    for row in db.execute('SELECT * FROM material_analysis_runs WHERE task_id=? ORDER BY created_at,run_id', (task,)):
        data = {key: value.decode('utf-8') if isinstance(value, bytes) else value for key, value in dict(row).items()}
        data = public_analysis_run(db, data, task)
        if data is not None:
            state = json.loads(data['payload'])
            scope = state['scope']
            if (scope['delivery_id'], scope['delivery_revision'], scope['snapshot_ref']) != (sample['delivery_id'], sample['delivery_revision'], sample['snapshot_ref']):
                raise ValueError('Supplement scope is not the selected delivery')
            refs.update((ref['id'], ref['version']) for ref in state['reports'])
            runs.append(data)
    if not runs:
        raise ValueError('No saved supplementary reports to publish')
    output.mkdir(parents=True, exist_ok=True)
    with lzma.open(source, 'rb') as original, lzma.open(target, 'wb', preset=3) as stream:
        header = next(original)
        tag, value = json.loads(header)
        if tag != 'header' or value.get('task_id') != task or value.get('snapshot_ref') != sample['snapshot_ref']:
            raise ValueError('Original sample header mismatch')
        stream.write(header)
        for line in original:
            if re.match(rb'^\["material_analysis_runs"\s*,', line):
                continue
            if re.match(rb'^\["objects",\{"task_id":"[^"]+","kind":"material_analysis",', line[:512]):
                continue
            stream.write(line)
        def write(table, data):
            stream.write((json.dumps([table, data], ensure_ascii=False, separators=(',', ':'))+'\n').encode('utf-8'))
        for object_id, version in sorted(refs):
            row = db.execute("SELECT * FROM objects WHERE task_id=? AND kind='material_analysis' AND object_id=? AND version=?", (task, object_id, version)).fetchone()
            data = {key: value.decode('utf-8') if isinstance(value, bytes) else value for key, value in dict(row).items()}
            report = json.loads(data['payload'])
            if report.get('snapshot_ref') != sample['snapshot_ref']:
                raise ValueError('Supplement scientific snapshot mismatch')
            write('objects', data)
        for data in runs:
            write('material_analysis_runs', data)
    with target.open('rb') as stream:
        pin = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {**entry, 'sha256': pin}


def append_followups(db, sample, source, entry, output):
    """Keep the authoritative archive lines and add only public saved follow-ups."""
    from astroquery_ai.runtime.demo_messages import public_messages
    task=sample['task_id']
    scope={'delivery_id':sample['delivery_id'],'delivery_revision':sample['delivery_revision'],'snapshot_ref':sample['snapshot_ref']}
    rows=public_messages(db,task,scope)
    if not rows: raise ValueError('No complete follow-up for the selected demo delivery')
    source,output=Path(source),Path(output)
    if source.resolve().parent==output.resolve():raise ValueError('Build separately before atomic publication')
    with source.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=entry['sha256']:raise ValueError('Original sample hash mismatch')
    output.mkdir(parents=True,exist_ok=True)
    target=output/source.name
    with lzma.open(source,'rb') as original,lzma.open(target,'wb',preset=3) as stream:
        for line in original:
            if not re.match(rb'^\["agent_messages"\s*,',line):stream.write(line)
        for row in rows:
            stream.write((json.dumps(['agent_messages',row],ensure_ascii=False,separators=(',',':'))+'\n').encode())
    with target.open('rb') as stream:pin=hashlib.file_digest(stream,'sha256').hexdigest()
    return {**entry,'sha256':pin,'public_messages':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime',type=Path)
    parser.add_argument('catalog',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    catalog=json.loads(args.catalog.read_bytes())['samples']
    args.output.mkdir(exist_ok=True,parents=True)
    root=(args.runtime/'runtime.sqlite3').resolve()
    with sqlite3.connect(root.as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        db.execute('BEGIN')
        entries={}
        for s in catalog:
            entries[s['task_id']]=build(db,s,args.output,pdf_urls(db,s['task_id']),args.runtime / 'artifacts')
            print(s['object'], 'packed', flush=True)
    (args.output/'index.json').write_text(json.dumps({'format':'published-demos/1','samples':entries},ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
