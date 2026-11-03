"""Read-only, exact-source presentation; never changes evidence or measurements."""
import re
import unicodedata
from astroquery_ai.runtime.codec import digest,loads

VERSION='EvidenceView/1'


def normalized(text):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',text))


def locate_excerpt(page,text):
    """Unique exact native text only. Repeated numbers and scans get no box."""
    needle=normalized(text or '')
    lines=page.get('layout_lines',[])
    if len(needle)<8 or not lines:return []
    if page.get('layout_rotation',0)!=0 and page.get('layout_coordinate_space')!='rendered_page_points':return []
    parts=[normalized(line['text']) for line in lines]
    haystack=''.join(parts)
    positions=[m.start() for m in re.finditer(re.escape(needle),haystack)]
    if len(positions)!=1:return []
    begin,end=positions[0],positions[0]+len(needle)
    cursor,boxes=0,[]
    for line,part in zip(lines,parts):
        if cursor<end and cursor+len(part)>begin:boxes.append(line['bbox'])
        cursor+=len(part)
    width,height=page.get('width'),page.get('height')
    if width and height and any(not (0<=b[0]<=b[2]<=width and 0<=b[1]<=b[3]<=height) for b in boxes):return []
    return boxes


def focus_record_views(conn, task_id, cutoff, source, record, views):
    """Add a reading aid only inside an already verified native line of the exact source PDF."""
    work_id = (source.get('work') or {}).get('work_id') or source.get('work_id') or source.get('source_id')
    raw = normalized(record.get('raw_value') or '')
    if not work_id or not raw or not any(char.isdigit() for char in raw):
        return views
    match = re.compile(r'(?<![\w.−+\-])' + re.escape(raw) + r'(?![\w.])')
    result = []
    for view in views:
        if view.get('kind') != 'pdf' or not any(p.get('bbox') for p in view.get('points', [])):
            result.append(view)
            continue
        row = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='document_index' "
            "AND object_id=? AND created_at<=? AND json_extract(CAST(payload AS TEXT),'$.sha256')=? "
            "ORDER BY version DESC LIMIT 1",
            (task_id, work_id, cutoff, view['artifact_ref'].get('content_sha256'))).fetchone()
        pages = {p['page']: p for p in loads(row[0])['pages']} if row else {}
        points = []
        for p in view['points']:
            page = pages.get(p['page'], {})
            boxes = p.get('bbox') or []
            hits = [line.get('bbox') for line in page.get('layout_lines', [])
                    for _ in match.finditer(normalized(line.get('text') or ''))] if boxes else []
            if len(hits) == 1 and hits[0] in boxes and page.get('width') == p.get('width') and page.get('height') == p.get('height'):
                p = {**p, 'value_line_bbox': hits[0]}
            points.append(p)
        result.append({**view, 'points': points})
    return result


def anchors(check):
    blocks={}
    def inventory(value):
        if isinstance(value,dict):
            if value.get('block_id') and isinstance(value.get('text'),str):blocks[value['block_id']]=value
            for child in value.values():inventory(child)
        elif isinstance(value,list):
            for child in value:inventory(child)
    inventory(check)
    result=[]
    def visit(value,role):
        if isinstance(value,dict):
            if type(value.get('page')) is int and (value.get('quote') or value.get('block_ids')):
                quoted=value.get('quote')
                selected=value.get('block_ids') or []
                if selected and all(k in blocks and blocks[k]['page']==value['page'] for k in selected):
                    block_text='\n'.join(blocks[k]['text'] for k in selected)
                    if not quoted or normalized(quoted) not in normalized(block_text):
                        quoted=block_text
                if quoted:result.append({'page':value['page'],'excerpt':quoted,'role':role})
            for key,child in value.items():
                if key!='saved_pages':visit(child,key if key not in {'check','context','anchor'} else role)
        elif isinstance(value,list):
            for child in value:visit(child,role)
    visit(check,'associated_evidence')
    return result


def review_evidence(repository, conn, task_id, ref, cutoff=None):
    """Attach reading labels and an existing whole-page preview to the pinned evidence."""
    item = repository.object(conn, task_id, 'evidence', ref['id'], ref['version'])
    deadline = cutoff or '9999'
    source = conn.execute("SELECT json_extract(CAST(payload AS TEXT),'$.title') FROM objects "
        "WHERE task_id=? AND kind='source' AND object_id=? AND created_at<=? ORDER BY version DESC LIMIT 1",
        (task_id, item.get('source_id'), deadline)).fetchone()
    title = source[0] if source else None
    if isinstance(title, str) and title.startswith('['):
        try:
            titles = loads(title)
            if isinstance(titles, list):
                title = ' · '.join(str(t) for t in titles if t)
        except ValueError:
            pass
    item = {**item, 'source_title': title}
    aid = (item.get('artifact_ref') or {}).get('id')
    page = (item.get('locator') or {}).get('page')
    if item.get('kind') == 'paper' and aid and type(page) is int and page > 0:
        key = digest({'artifact_id': aid, 'page': page})
        row = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='evidence_page_preview' "
            "AND object_id=? AND created_at<=? ORDER BY version DESC LIMIT 1", (task_id, key, deadline)).fetchone()
        if row:
            preview = loads(row[0])
            if preview.get('pdf_artifact_id') == aid and preview.get('page') == page:
                item['page_preview'] = preview.get('artifact')
    return item


def table_view(evidence,source,selected_columns=()):
    try:raw=loads(evidence['raw_text'])
    except (ValueError,TypeError):return None
    if not isinstance(raw,dict) or not isinstance(raw.get('cells'),dict):return None
    locator=evidence['locator'];columns={c['name']:c for c in source.get('metadata',{}).get('columns',[])}
    columns.update({c['name']:c for c in raw.get('columns',[])})
    selected={locator.get('column'),*selected_columns}
    return {'schema_version':VERSION,'evidence_id':evidence['evidence_id'],
        'artifact_ref':evidence['artifact_ref'],'kind':'table','table':locator.get('table'),
        'row':locator.get('row'),'row_basis':'attachment_data_row' if source.get('kind')=='official_attachment' else 'query_response_row',
        'column':locator.get('column'),
        'cells':[{'column':key,'raw':val,'metadata':columns.get(key,{}),
                  'is_main':key==locator.get('column'),'is_selected':key in selected} for key,val in raw['cells'].items()],
        'readme':source.get('readme') or source.get('metadata',{}).get('catalog_document'),
        'parent_work_id':source.get('work_id'),'precision':'exact_saved_cells'}


def build_views(repository,conn,tid,evidence,sources,*,snapshot=None,cutoff=None):
    source_map={s['source_id']:s for s in sources}
    papers=[e for e in evidence if e.get('locator',{}).get('page') and e.get('artifact_ref')]
    indexes=[]; previews=[]
    if papers and snapshot is not None:
        for sha in {e['artifact_ref']['content_sha256'] for e in papers}:
            rows=conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='document_index' "
                "AND created_at<=? AND json_extract(CAST(payload AS TEXT),'$.sha256')=? ORDER BY version DESC",
                (tid,cutoff,sha))
            indexes.extend(loads(r[0]) for r in rows)
        ids={e['artifact_ref']['id'] for e in papers}
        for row in conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='evidence_page_preview' AND created_at<=?",(tid,cutoff)):
            item=loads(row[0])
            if item.get('pdf_artifact_id') in ids:previews.append(item)
    elif papers:
        indexes=repository.objects(conn,tid,'document_index')
        previews=repository.objects(conn,tid,'evidence_page_preview')
    records=[];interpretations={}
    if any(e.get('text_origin')=='original_cells' for e in evidence):
        records=snapshot['measurements'] if snapshot is not None else repository.objects(conn,tid,'measurement')
        rows=snapshot['provenance_bundle']['interpretations'] if snapshot is not None else repository.objects(conn,tid,'interpretation')
        interpretations={i['interpretation_id']:i for i in rows}

    results=[]
    for item in evidence:
        if item.get('text_origin')=='original_cells':
            selected=[]
            for record in records:
                if not any(r['id']==item['evidence_id'] for r in record['evidence_refs']):continue
                proposal=interpretations.get(record['interpretation_ref']['id'],{}).get('proposal',{})
                selected.extend(e.get('location') for e in proposal.get('errors',[]))
                selected.extend(e.get('column') for e in proposal.get('catalog_field_roles',[]))
                selected.extend(e.get('location') for e in proposal.get('source_references',[]))
            view=table_view(item,source_map.get(item['source_id'],{}),selected)
            if view:results.append(view)
            continue
        if not item.get('locator',{}).get('page'):continue
        matching=[i for i in indexes if i.get('sha256')==item['artifact_ref']['content_sha256']]
        index=max(matching,key=lambda i:sum(p.get('layout_coordinate_space')=='rendered_page_points'
            for p in i.get('pages',[])),default={})
        pages={p['page']:p for p in index.get('pages',[])}
        points=[{'page':item['locator']['page'],'excerpt':item['raw_text'],'role':'main_excerpt'},
            *anchors(item.get('local_admission_check',{}))]
        seen,set_points={},[]
        for point in points:
            key=digest({'page':point['page'],'excerpt':point['excerpt']})
            if key in seen:
                if point['role'] not in seen[key]['roles']:seen[key]['roles'].append(point['role'])
                continue
            page=pages.get(point['page'],{})
            boxes=locate_excerpt(page,point['excerpt'])
            preview=next((p for p in previews if p['pdf_artifact_id']==item['artifact_ref']['id'] and p['page']==point['page']),{})
            current={**point,'roles':[point['role']],'bbox':boxes,'width':page.get('width'),'height':page.get('height'),
                'preview_artifact':preview.get('artifact'),
                'precision':'unique_native_lines' if boxes else 'physical_page_only',
                'notice':None if boxes else '未能唯一定位原文坐标；摘录可能为模型转写，请核对原页。'}
            seen[key]=current;set_points.append(current)
        results.append({'schema_version':VERSION,'evidence_id':item['evidence_id'],
            'kind':'pdf','artifact_ref':item['artifact_ref'],'page_basis':'physical_pdf_page','points':set_points})
    return results
