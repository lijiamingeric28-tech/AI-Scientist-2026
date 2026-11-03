"""CDS-curated article tables, qualified by their primary ReadMe citation.

Metadata search is discovery only: a reference in Abstract/See also never
establishes that a dataset is an attachment of the selected scientific work.
"""
import hashlib
import re

from astroquery_ai.runtime.errors import DomainError
from .catalog_document import readme_url


def archive_links(raw, catalog_id, table_ids, expected_bibcodes, *, artifact_ref=None):
    url = readme_url(catalog_id, next(iter(table_ids), catalog_id + '/_'))
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeError as exc:
        raise DomainError('CDS_README_ENCODING', '官方目录说明编码不支持') from exc
    if len(raw) > 256 * 1024:
        raise DomainError('CDS_README_LIMIT', '官方目录说明超过大小限制')
    lines = text.splitlines()
    if not lines or not lines[0].startswith(catalog_id + ' '):
        raise DomainError('OFFICIAL_ARCHIVE_UNVERIFIED', '目录说明未声明实际目录标识')
    header = re.split(r'^\s*(?:ADC_Keywords|Keywords|Abstract|Description|File Summary|See also):', text,
                      maxsplit=1, flags=re.M)[0]
    primary = set(re.findall(r'^\s*=([0-9]{4}[A-Za-z0-9.&+]{14}[A-Za-z])\s', header, re.M))
    matching = sorted(primary & set(expected_bibcodes))
    if not matching:
        raise DomainError('OFFICIAL_PARENT_UNVERIFIED', '目录主引文未对应已选作品；参考文献不算关联')
    association = {'rule_id': 'cds-primary-readme-publication-1', 'parent_bibcodes': matching,
        'catalog_id': catalog_id, 'landing_url': url, 'landing_sha256': hashlib.sha256(raw).hexdigest(),
        'landing_artifact_ref': artifact_ref, 'locator': 'ReadMe primary publication header and explicit byte-layout file declaration'}
    links = [{'url': url, 'format': 'readme', 'association': association}]
    rejected = []
    # Only explicitly described, non-wildcard files. Do not enumerate referenced
    # catalogs, SED directories or arbitrary archive links.
    for match in re.finditer(r'^Byte-by-byte Description of (?:file|output)s?:\s*(.+)$', text, re.M):
        for name in re.findall(r'(?<![\w/.+*-])([\w+.-]+\.(?:dat|sam|fit|fits|csv|tsv|vot|xml|tbl))(?![\w.*-])', match[1]):
            if name in {'.', '..'} or '/' in name:
                continue
            from .attachments import FORMATS
            suffix = '.' + name.rsplit('.', 1)[-1].lower()
            format = FORMATS.get(suffix)
            if not format:
                continue
            candidate = {'url': url.rsplit('/', 1)[0] + '/' + name, 'format': format,
                'association': {**association, 'declared_filename': name, 'layout_header': match[0]}}
            if candidate['url'] not in {item['url'] for item in links}:
                links.append(candidate)
    return links[:12], rejected + [{'url': item['url'], 'reason': 'attachment_candidate_limit'} for item in links[12:]]
