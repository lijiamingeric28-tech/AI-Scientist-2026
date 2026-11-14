"""Official association checks and bounded local structured-table decoding."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from fnmatch import fnmatchcase
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from astroquery_ai.runtime.errors import DomainError
from .literature import normalize_doi
from .catalogs import exact_rows, parse_votable

FORMATS = {
    ".pdf": "pdf",
    ".csv": "csv",
    ".tsv": "tsv",
    ".fits": "fits",
    ".fit": "fits",
    ".fts": "fits",
    ".vot": "votable",
    ".xml": "votable",
    ".dat": "mrt",
    ".txt": "mrt",
    ".tbl": "mrt",
}
CONTAINERS = {".zip", ".tar", ".gz", ".tgz"}


class OfficialPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.dois, self.links, self.stack = [], [], []
        self.blocks, self.anchors = [], []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "meta" and (values.get("name") or values.get("property") or "").lower() in {
            "citation_doi",
            "dc.identifier",
            "dc.identifier.doi",
            "prism.doi",
        }:
            try:
                self.dois.append(normalize_doi(values.get("content", "")))
            except ValueError:
                pass
        metadata_name = (values.get('name') or values.get('property') or '').lower()
        if tag == 'meta' and metadata_name in {
            'citation_supplementary_material', 'citation_supplementary_material_url',
            'citation_data_url',
        } and values.get('content'):
            self.links.append({'href': values['content'], 'basis': metadata_name,
                               'text': '', 'media_type': values.get('type')})
        markers = " ".join(
            values.get(k, "") for k in ("id", "class", "rel", "data-section", 'itemprop')
        ).lower()
        associated = ('supplement' in markers or 'associatedmedia' in markers
                      or any(active for _, active in self.stack))
        if tag in {'p', 'li', 'section', 'article', 'div'}:
            self.blocks.append({'tag': tag, 'text': [], 'links': []})
        if tag == "a" and values.get("href"):
            link = {'href': values['href'], 'text': '', 'media_type': values.get('type'),
                    'basis': 'supplement-scoped HTML link' if associated else None}
            self.links.append(link)
            self.anchors.append(link)
            for block in self.blocks:
                block['links'].append(link)
        if tag not in {
            "meta",
            "link",
            "br",
            "hr",
            "img",
            "input",
            "source",
            "wbr",
            "area",
            "base",
            "embed",
            "param",
            "track",
            "col",
        }:
            self.stack.append((tag, associated))

    def handle_endtag(self, tag):
        if tag == 'a' and self.anchors:
            self.anchors.pop()
        for index in range(len(self.blocks) - 1, -1, -1):
            if self.blocks[index]['tag'] == tag:
                # Prefer the closest explanatory block, never the whole page.
                for block in reversed(self.blocks[index:]):
                    context = ' '.join(' '.join(block['text']).split())
                    if len(context) <= 2400:
                        for link in block['links']:
                            link.setdefault('nearby_text', context)
                del self.blocks[index:]
                break
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        for link in self.anchors:
            link['text'] += data
        for block in self.blocks:
            block['text'].append(data)


def _supplement_declaration(text):
    # Publication-link conventions, not scientific quantity interpretation.
    return bool(re.search(r'\b(supplement(?:ary|al)?(?:\s+(?:material|data|information))?'
                          r'|supporting\s+information|machine[ -]readable\s+table'
                          r'|source\s+data)\b', text, re.I))


def official_links(
    html: bytes, page_url: str, expected_dois: list[str]
) -> tuple[list[dict], list[dict]]:
    try:
        text = html.decode("utf-8-sig")
    except UnicodeError as exc:
        raise DomainError("LANDING_ENCODING_UNSUPPORTED", "作品落地页编码暂不支持") from exc
    parser = OfficialPage()
    parser.feed(text)
    matching = sorted(set(parser.dois) & set(expected_dois))
    if not matching:
        raise DomainError("OFFICIAL_PARENT_UNVERIFIED", "落地页未明确声明所选作品的DOI")
    accepted, rejected = [], []
    seen = set()
    for link in parser.links:
        href = link['href']
        url = urljoin(page_url, href)
        parts = urlsplit(url)
        suffix = Path(parts.path).suffix.lower()
        format = (
            "container"
            if suffix in CONTAINERS
            else "readme"
            if Path(parts.path).name.lower() == "readme"
            else FORMATS.get(suffix)
        )
        text = ' '.join(link.get('text', '').split())
        nearby = link.get('nearby_text', '')
        basis = link.get('basis')
        # A literal declaration on the DOI-verified article is sufficient;
        # a generic table/file link or same host by itself is not association.
        if not basis and _supplement_declaration(text):
            basis = 'explicit supplementary/data anchor text'
        if not basis and _supplement_declaration(nearby) and len(nearby) <= 800:
            if format is not None or link.get('media_type'):
                basis = 'nearby explicit supplementary/data declaration'
        if not basis:
            if format is not None:
                rejected.append({'url': url, 'reason': 'candidate_association_unresolved',
                                 'link_text': text, 'nearby_text': nearby})
            continue
        if url in seen:
            continue
        seen.add(url)
        if parts.scheme != "https" or parts.username or parts.password:
            rejected.append(
                {
                    "url": url,
                    "reason": "unsupported_or_unqualified_attachment_url",
                }
            )
            continue
        # Extensionless official downloads are candidates. The acquired bytes
        # and response media type must still pass the ordinary format parser.
        format = format or 'pending'
        accepted.append(
            {
                "url": parts._replace(fragment="").geturl(),
                "format": format,
                'declared_media_type': link.get('media_type'),
                "association": {
                    "rule_id": "verified-doi-official-supplement-link-2",
                    "parent_dois": matching,
                    "landing_url": page_url,
                    "landing_sha256": hashlib.sha256(html).hexdigest(),
                    "locator": basis,
                    'literal_href': href, 'link_text': text, 'nearby_text': nearby,
                },
            }
        )
    return accepted, rejected


def acquired_format(raw: bytes, candidate: dict, metadata: dict) -> str:
    """Verify real bytes; an URL extension is never an acquired file's proof."""
    lead = raw.lstrip()[:4096]
    if lead.startswith(b'%PDF-'):
        return 'pdf'
    if re.search(br'<\s*(?:html|!doctype\s+html)\b', lead, re.I):
        raise DomainError('ATTACHMENT_ACTUAL_FORMAT', '附件链接实际返回网页，未取得支持的结构化文件')
    if raw.startswith(b'PK\x03\x04') or raw.startswith(b'\x1f\x8b') or raw[257:262] == b'ustar':
        return 'container'
    if raw.startswith(b'SIMPLE  ='):
        return 'fits'
    if re.search(br'<(?:[\w.-]+:)?VOTABLE\b', lead, re.I):
        return 'votable'
    declared = (metadata.get('media_type') or candidate.get('declared_media_type') or '').split(';')[0].lower()
    fmt = candidate['format']
    if fmt == 'readme':
        return fmt
    if fmt in {'csv', 'tsv', 'mrt'}:
        raw.decode('utf-8-sig')
        return fmt  # table structure is independently checked by M03
    by_media = {'text/csv': 'csv', 'text/tab-separated-values': 'tsv',
                'application/x-mrt': 'mrt'}
    if declared in by_media:
        raw.decode('utf-8-sig')
        return by_media[declared]
    if b'Byte-by-byte Description' in raw[:65536]:
        return 'mrt'
    raise DomainError('ATTACHMENT_ACTUAL_FORMAT', '实际文件类型未能确认为已支持的结构化格式')


def structured_table(
    path: Path,
    format: str,
    table_id: str,
    *,
    header_only=False,
    id_column=None,
    namespace=None,
    aliases=None,
    candidate_patterns=None,
    maximum_rows=1000,
    row_offset=0,
    readme_text=None,
    original_filename=None,
    hdu=None,
):
    if path.stat().st_size > 32 * 1024**2 or format not in set(FORMATS.values()):
        raise DomainError("ATTACHMENT_FORMAT_LIMIT", "附件格式或大小超出支持范围")
    if type(maximum_rows) is not int or not 1 <= maximum_rows <= 1000:
        raise DomainError("ATTACHMENT_ROW_LIMIT", "附件返回行数上限无效")
    if type(row_offset) is not int or not 0 <= row_offset <= 1_000_000:
        raise DomainError('ATTACHMENT_ROW_OFFSET', '附件续读起点无效')
    if candidate_patterns is not None and (not id_column or not isinstance(candidate_patterns, list)
            or any(not isinstance(p, str) or not p or any(c not in '*0123456789' for c in p)
                   for p in candidate_patterns)):
        raise DomainError('ATTACHMENT_CANDIDATE_PATTERN', '标识候选导航模式无效')

    def selected(row):
        if not id_column:
            return True
        if candidate_patterns:
            cell = row.get(id_column)
            # Navigation only. The ordinary M03 consumer must still establish
            # the actual subject from source evidence after parsing.
            return isinstance(cell, str) and any(fnmatchcase(cell, p) for p in candidate_patterns)
        return bool(exact_rows([row], [id_column], aliases or [], {id_column: namespace} if namespace else None))
    raw = path.read_bytes()
    if raw.startswith(b"%PDF-"):
        raise DomainError("SUPPLEMENTARY_PDF_EXCLUDED", "补充PDF不进入结构化附件通道")
    columns, all_rows, row_numbers = [], [], []
    matched_count = 0

    def append_selected(row, number):
        nonlocal matched_count
        matched_count += 1
        if matched_count > row_offset and len(all_rows) < maximum_rows + 1:
            all_rows.append(row)
            row_numbers.append(number)
    literal_rows, literal_units, source_formats, source_nulls = None, {}, {}, {}
    total = None if header_only else 0
    file_subject_context = None
    if format in {"csv", "tsv"}:
        reader = csv.DictReader(
            io.StringIO(raw.decode("utf-8-sig"), newline=""),
            delimiter="," if format == "csv" else "\t",
        )
        if (
            not reader.fieldnames
            or len(reader.fieldnames) != len(set(reader.fieldnames))
            or len(reader.fieldnames) > 2000
            or any(not name for name in reader.fieldnames)
        ):
            raise DomainError("ATTACHMENT_COLUMNS", "附件表头为空、重复或过大")
        columns = [
            {
                "name": name,
                "id": name,
                "datatype": "char",
                "unit_text": None,
                "ucd": None,
                "arraysize": "*",
                "description": name,
                "null": None,
            }
            for name in reader.fieldnames
        ]
        if not header_only:
            for row in reader:
                total += 1
                if total > 1_000_000 or None in row or any(value is None for value in row.values()):
                    raise DomainError("ATTACHMENT_ROW_SHAPE", "附件行结构或解析行数超限")
                if not selected(row):
                    continue
                append_selected(row, total - 1)
    else:
        from astropy.table import Table

        if format == "votable":
            if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                raise DomainError("EXTERNAL_TABLE_STREAM", "附件不能引用未取得的外部数据流")
            tree = ET.fromstring(raw)
            if any(
                node.tag.rsplit("}", 1)[-1].upper() == "STREAM"
                and any(key.rsplit("}", 1)[-1].lower() == "href" for key in node.attrib)
                for node in tree.iter()
            ):
                raise DomainError("EXTERNAL_TABLE_STREAM", "附件不能引用未取得的外部数据流")
            parsed = parse_votable(raw, allow_unnamed=True)
            tables = [t for resource in parsed["resources"] for t in resource["tables"]]
            if len(tables) != 1:
                raise DomainError(
                    "ATTACHMENT_TABLE_SELECTION", "多表附件须明确具体表，当前不能自动选第一表"
                )
            original = tables[0]
            if not original["binary_data"]:
                columns, all_rows = original["columns"], original["rows"] if not header_only else []
                total = None if header_only else len(all_rows)
                row_numbers = list(range(len(all_rows)))
                if id_column:
                    indices = [i for i, row in enumerate(all_rows) if selected(row)]
                    all_rows = [all_rows[i] for i in indices]
                    row_numbers = indices
                return {
                    "resources": [
                        {
                            "resource_id": table_id,
                            "description": original["description"],
                            "tables": [
                                {
                                    **original,
                                    "table_id": table_id,
                                    "rows": all_rows[row_offset:row_offset+maximum_rows],
                                    "source_row_numbers": row_numbers[row_offset:row_offset+maximum_rows],
                                }
                            ],
                        }
                    ],
                    "response_sha256": hashlib.sha256(raw).hexdigest(),
                    "overflow": parsed["overflow"] or len(all_rows) > row_offset + maximum_rows,
                    "source_overflow": parsed['overflow'],
                    "next_row_offset": row_offset + maximum_rows if len(all_rows) > row_offset + maximum_rows else None,
                    "matched_rows": len(all_rows),
                    "total_rows": total,
                }
            table = Table.read(io.BytesIO(raw), format="votable")
        elif format == "fits":
            from astropy.io import fits

            with fits.open(io.BytesIO(raw), memmap=False) as file:
                tables = [(i, extension) for i, extension in enumerate(file)
                          if isinstance(extension, (fits.BinTableHDU, fits.TableHDU))]
                if hdu is not None:
                    if type(hdu) is not int:
                        raise DomainError('ATTACHMENT_HDU_SELECTION','FITS扩展标识必须是原文件中的整数位置')
                    tables = [(i, extension) for i, extension in tables if i == hdu]
                if len(tables) != 1:
                    raise DomainError("ATTACHMENT_TABLE_SELECTION", "FITS附件须有唯一明确的科学表")
                selected_hdu, extension = tables[0]
                table = Table(extension.data)
                file_subject_context = {'hdu':selected_hdu,'extension_name':extension.name,
                    'primary_header':[{ 'key':k,'value':str(file[0].header[k]),'comment':file[0].header.comments[k]}
                                      for k in ('OBJECT','NAME','TARGET','GAIA_DR3_SOURCE_ID') if k in file[0].header]}
                for n,column in enumerate(extension.columns,1):
                    literal_units[column.name] = column.unit
                    if column.unit:
                        table[column.name].unit = column.unit
                    table[column.name].description = extension.header.comments['TTYPE'+str(n)] or column.name
        else:
            from astropy.io import ascii

            if readme_text is not None:
                if (
                    not isinstance(readme_text, str)
                    or len(readme_text.encode("utf-8")) > 256 * 1024
                    or not original_filename
                    or Path(original_filename).name != original_filename
                ):
                    raise DomainError("CDS_README_SCOPE", "CDS说明或对应文件名不合格")
                reader = ascii.get_reader(reader_cls=ascii.Cds, readme=readme_text.splitlines())
                reader.data.table_name = original_filename
                lines = raw.decode("utf-8-sig").splitlines()
                try:
                    table = reader.read(lines)
                except ValueError as exc:
                    if 'Column ' not in str(exc) or 'failed to convert' not in str(exc):
                        raise
                    # Real CDS tables can carry literal placeholders in a
                    # numeric field without an Astropy-compatible null token.
                    # Do not infer zero/null or discard the table. Header/byte
                    # parsing has succeeded; retain its exact string cells and
                    # declared source formats for the ordinary semantic stage.
                    values = list(reader.data.get_str_vals())
                    names = [col.name for col in reader.header.cols]
                    if len(values) > 1_000_000 or any(len(row) != len(names) for row in values):
                        raise DomainError('ATTACHMENT_ROW_SHAPE', '原始定宽行与字段数不一致') from exc
                    table = Table(rows=values, names=names, dtype=[str] * len(names))
                    for col in reader.header.cols:
                        table[col.name].unit = getattr(col, 'unit', None)
                        table[col.name].description = getattr(col, 'description', None)
            else:
                reader = ascii.get_reader(reader_cls=ascii.Mrt)
                table = reader.read(raw.decode("utf-8-sig").splitlines())
            # Astropy's numeric output normalizes 1.000, 1e-03 and long integer
            # literals. Keep original fixed-width cells before conversion or
            # null substitutions; parsed numeric values are not source text.
            literal_rows = [dict(zip(table.colnames, values, strict=True))
                            for values in reader.data.get_str_vals()]
            if len(literal_rows) != len(table):
                raise DomainError('ATTACHMENT_ROW_SHAPE', '原始定宽行与解析行数不一致')
            source_formats = {col.name: col.raw_type for col in reader.header.cols}
            source_nulls = {col.name: getattr(col, 'null', None) for col in reader.header.cols}
            from .catalog_document import parse_readme
            filename = original_filename or table_id.rsplit('/', 1)[-1]
            layout = parse_readme(readme_text or raw.decode('utf-8-sig'), filename.rsplit('.', 1)[0])
            for name, spans in layout.get('fields', {}).items():
                if len(spans) == 1:
                    literal_units[name] = None if spans[0]['unit_token'] == '---' else spans[0]['unit_token']
        if len(table.colnames) > 2000:
            raise DomainError("ATTACHMENT_COLUMNS", "附件列数超过上限")
        columns = [
            {
                "name": name,
                "id": name,
                "datatype": ('char' if source_formats.get(name, '').startswith('A') else
                    'long' if source_formats.get(name, '').startswith('I') else
                    'double' if source_formats.get(name, '')[:1] in {'F', 'E', 'D'} else str(table[name].dtype)),
                "source_format": source_formats.get(name),
                "unit_text": literal_units.get(name, str(table[name].unit) if table[name].unit else None),
                "ucd": None,
                "arraysize": None,
                "description": table[name].description or name,
                "null": source_nulls.get(name),
            }
            for name in table.colnames
        ]
        total = len(table)
        if not header_only:
            if total > 1_000_000:
                raise DomainError("ATTACHMENT_ROW_LIMIT", "附件解析行数超过上限")
            import numpy as np

            for number, original in enumerate(table):
                row = {
                    name: ""
                    if np.ma.is_masked(original[name])
                    or isinstance(original[name], (float, np.floating))
                    and np.isnan(original[name])
                    else original[name].decode("utf-8")
                    if isinstance(original[name], bytes)
                    else str(original[name])
                    for name in table.colnames
                }
                if literal_rows is not None:
                    row = literal_rows[number]
                if not selected(row):
                    continue
                append_selected(row, number)
    return {
        "resources": [
            {
                "resource_id": table_id,
                "description": "Official structured attachment",
                "tables": [
                    {
                        "table_id": table_id,
                        "columns": columns,
                        "description": "Original attachment columns and cells",
                        "rows": all_rows[:maximum_rows],
                        "source_row_numbers": row_numbers[:maximum_rows],
                        "binary_data": False,
                        **({'file_subject_context':file_subject_context} if file_subject_context else {}),
                    }
                ],
            }
        ],
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "overflow": len(all_rows) > maximum_rows,
        "next_row_offset": row_offset + maximum_rows if len(all_rows) > maximum_rows else None,
        "matched_rows": matched_count,
        "total_rows": total,
    }
