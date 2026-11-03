"""Read CDS byte-layout descriptions and their local notes without inventing semantics."""
import re
from functools import lru_cache
from pathlib import PurePosixPath

from astroquery_ai.runtime.codec import digest
from astroquery_ai.runtime.errors import DomainError


def readme_url(catalog_id, table_id):
    # Both identifiers are from the actual VOTable RESOURCE/TABLE, not model URLs.
    if (not isinstance(catalog_id, str) or not table_id.startswith(catalog_id + '/')
            or not re.fullmatch(r'[A-Za-z0-9+_.-]+(?:/[A-Za-z0-9+_.-]+)+', catalog_id)
            or any(part in {'.', '..'} for part in catalog_id.split('/'))):
        raise DomainError('CATALOG_DOCUMENT_ASSOCIATION_UNKNOWN', '实际目录标识不足以建立官方ReadMe关联')
    return 'https://cdsarc.cds.unistra.fr/ftp/cats/' + catalog_id + '/ReadMe'


def parse_readme(text, table_id, *, columns=None):
    text_view=None
    if re.search(r'<pre\b',text,re.I):
        from html.parser import HTMLParser
        class PreText(HTMLParser):
            def __init__(self):super().__init__(convert_charrefs=True);self.depth=0;self.blocks=[]
            def handle_starttag(self,tag,attrs):
                if tag=='pre':
                    if not self.depth:self.blocks.append([])
                    self.depth+=1
                elif tag=='br' and self.depth:self.blocks[-1].append('\n')
            def handle_endtag(self,tag):
                if tag=='pre':self.depth=max(0,self.depth-1)
            def handle_data(self,data):
                if self.depth:self.blocks[-1].append(data)
        parser=PreText();parser.feed(text)
        blocks=[''.join(b).strip('\r\n') for b in parser.blocks]
        matches=[b for b in blocks if re.search(r'^Byte-by-byte Description of ',b,re.M)]
        if len(matches)==1:
            from hashlib import sha256
            text_view={'kind':'official_HTML_pre_text','line_coordinate':'decoded_pre_text',
                       'original_utf8_sha256':sha256(text.encode()).hexdigest(),'raw_HTML_retained':True}
            text=matches[0]
    lines = text.splitlines()
    heading = re.match(r'^([A-Z]+(?:/[^\s/]+)+)\s', lines[0]) if lines else None
    # Local official attachments use a filename/layout selector; acquisition
    # already binds their parent ReadMe. Only a full catalog/table identifier
    # asserts a catalog identity here. A basename is not a different catalog.
    expected_catalog = table_id.rsplit('/', 1)[0] if '/' in table_id else None
    if heading and expected_catalog is not None and heading[1] != expected_catalog:
        return {'schema_version': 'CDSReadMeContext/1', 'table_id': table_id,
            'state': 'catalog_identity_mismatch', 'fields': {}, 'notes': {},
            'expected_catalog': expected_catalog, 'actual_catalog': heading[1]}
    headers = [(i, m[1]) for i, line in enumerate(lines)
               if (m := re.match(r'^Byte-by-byte Description of (?:file|output)s?:\s*(.+)$', line))]
    table_name = table_id.rsplit('/', 1)[-1]
    matches = [(n, i, files) for n, (i, files) in enumerate(headers)
               if any(PurePosixPath(f).name.split('.')[0] == table_name
                      for f in re.findall(r'[\w+.-]+\.(?:dat|sam|fit|fits)(?:\.gz)?', files))]
    if len(matches) != 1:
        return {'schema_version': 'CDSReadMeContext/1', 'table_id': table_id,
            'state': 'table_layout_not_identified', 'fields': {}, 'notes': {},
            'available_layout_headers': [{'line': i + 1, 'text': files} for i, files in headers]}
    ordinal, start, files = matches[0]
    end = headers[ordinal + 1][0] if ordinal + 1 < len(headers) else len(lines)
    fields, notes = {}, {}
    active = None
    for index in range(start + 1, end):
        line = lines[index]
        note = re.match(r'^Note \(([^)]+)\):', line)
        field = re.match(r'^\s*\d+(?:\s*-\s*\d+)?\s+(?P<format>\S+)\s+(?P<unit>\S+)\s+(?P<label>\S+)\s+(?P<description>.+)$', line)
        if note:
            active = {'line_start': index + 1, 'line_end': index + 1, 'text': line}
            # Duplicate labels stay ambiguous rather than taking the last one.
            notes.setdefault(note[1], []).append(active)
        elif field and not notes:
            active = {'line_start': index + 1, 'line_end': index + 1, 'text': line,
                'unit_token': field['unit'], 'source_format': field['format'], 'description_text': field['description']}
            fields.setdefault(field['label'], []).append(active)
        elif active is not None and (not line.strip() or line[:1].isspace()):
            active['text'] += '\n' + line
            if 'description_text' in active:
                active['description_text'] += ' ' + line.strip()
            active['line_end'] = index + 1
        elif active is not None:
            active = None
    joined = []
    if columns:
        # VizieR may publish a joined view under one table ID. A field in
        # another layout is usable only by unique exact label AND unchanged
        # native column description, with its real layout retained explicitly.
        other_layouts = []
        for _, other_files in headers:
            for filename in re.findall(r'[\w+.-]+\.(?:dat|sam|fit|fits)(?:\.gz)?', other_files):
                name = PurePosixPath(filename).name.split('.')[0]
                if name != table_name:
                    other = parse_readme(text, table_id.rsplit('/', 1)[0] + '/' + name)
                    if other['state'] == 'table_layout_identified':
                        other_layouts.append(other)
        for column in columns:
            if column['name'] in fields or not column.get('description'):
                continue
            description = ' '.join(column['description'].split())
            candidates = [(other, span) for other in other_layouts for span in other['fields'].get(column['name'], [])
                if ' '.join(span.get('description_text', '').split()) == description]
            if len(candidates) == 1:
                other, span = candidates[0]
                fields[column['name']] = [{**span, 'source_layout': other['file_header'],
                    'association': 'unique_exact_label_and_native_description_in_same_catalog'}]
                joined.append({'column': column['name'], 'source_layout': other['file_header'],
                    'native_description': column['description'], 'rule': 'same-catalog-exact-description-1'})
                for key, values in other['notes'].items():
                    if key not in notes:
                        notes[key] = values
                    elif notes[key] != values:
                        notes[key] = [*notes[key], *[v for v in values if v not in notes[key]]]
    return {'schema_version': 'CDSReadMeContext/1', 'table_id': table_id,
        **({'text_view':text_view} if text_view else {}),
        'state': 'table_layout_identified', 'file_header': files, 'layout_line': start + 1,
        'catalog_scope': {'line_start': 1, 'line_end': headers[0][0], 'text': '\n'.join(lines[:headers[0][0]])},
        'fields': fields, 'notes': notes, 'joined_view_field_associations': joined}


@lru_cache(maxsize=2048)
def _referenced_names(names, text):
    return frozenset(name for name in names
                     if re.search(r'(?<![\w])' + re.escape(name) + r'(?![\w])', text))


def document_view(document, selected, all_names):
    """Expand literal note/field references; every snippet keeps its original lines."""
    parsed = document.get('parsed', {})
    fields, notes = parsed.get('fields', {}), parsed.get('notes', {})
    selected = set(selected)
    linked, note_ids = set(), set()
    # Each literal field/note is visited once. Rescanning the whole growing
    # closure for every edge made real cross-linked CDS ReadMes monopolize the
    # scheduler for minutes. Cached matching preserves overlapping field names.
    pending = [('field', name) for name in sorted(selected)]
    seen = set()
    names = tuple(all_names)
    while pending:
        kind, key = pending.pop()
        if (kind, key) in seen:
            continue
        seen.add((kind, key))
        snippets = (fields if kind == 'field' else notes).get(key, [])
        for span in snippets:
            for note in re.findall(r'\(([A-Za-z]*\d+)\)', span['text']):
                if note in notes and note not in note_ids:
                    note_ids.add(note)
                    pending.append(('note', note))
            for name in _referenced_names(names, span['text']):
                linked.add(name)
                if name not in selected:
                    selected.add(name)
                    pending.append(('field', name))
    return {'document_ref': document.get('document_ref'), 'artifact_ref': document.get('artifact_ref'),
        'origin_url': document.get('origin_url'), 'state': parsed.get('state', document.get('state', 'unavailable')),
        **({'text_view':parsed['text_view']} if parsed.get('text_view') else {}),
        'file_header': parsed.get('file_header'), 'referenced_column_names': sorted(linked),
        'catalog_scope': parsed.get('catalog_scope'),
        'field_descriptions': {name: fields[name] for name in sorted(selected) if name in fields},
        'notes': {key: notes[key] for key in sorted(note_ids)},
        'unmapped_column_names': sorted(selected - fields.keys()),
        'semantics': 'Literal CDS ReadMe excerpts, not an independently approved interpretation. Missing layout labels are not guessed aliases.'}


def document_key(catalog_id):
    return 'catalog-document-' + digest(catalog_id)


def select_cached_document(existing, candidate):
    """Resolve concurrent fetches without overwriting source bytes or receipts."""
    if existing is None:
        return {**candidate, 'revision': 1}, True, False
    if existing['state'] != 'acquired' and candidate['state'] == 'acquired':
        return {**candidate, 'revision': existing.get('revision', 1) + 1}, True, False
    if existing['state'] == candidate['state'] == 'acquired':
        if existing['artifact_ref']['content_sha256'] != candidate['artifact_ref']['content_sha256']:
            return existing, False, True
    return existing, False, False
