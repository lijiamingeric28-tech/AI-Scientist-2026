"""CDS-curated article tables, qualified by their primary ReadMe citation.

Metadata search is discovery only: a reference in Abstract/See also never
establishes that a dataset is an attachment of the selected scientific work.
"""
import hashlib
import re

from astroquery_ai.runtime.errors import DomainError
from .catalog_document import readme_url


def metadata_export_links(raw, expected_bibcodes, *, artifact_ref):
    """Official export fallback, qualified by RESOURCE-level data-origin cites.

    A bibcode merely mentioned in a description or LINK is not enough. Preserve
    the actual service representation; never label an export as a native .dat.
    """
    from xml.etree import ElementTree as ET
    from urllib.parse import urlencode
    from .catalogs import parse_votable
    parsed = parse_votable(raw)
    resources = {r['resource_id']: r for r in parsed['resources']}
    candidates = []
    for node in ET.fromstring(raw).iter():
        if node.tag.rsplit('}', 1)[-1] != 'RESOURCE':
            continue
        catalog = node.get('name') or node.get('ID')
        if catalog not in resources or not str(catalog).startswith('J/'):
            continue
        info = {n.get('name'): n.get('value') for n in node
                if n.tag.rsplit('}', 1)[-1] == 'INFO'}
        cited = (info.get('cites') or '').removeprefix('bibcode:')
        if cited not in expected_bibcodes:
            continue
        for table in resources[catalog]['tables']:
            tid = table['table_id']
            if not tid.startswith(catalog + '/'):
                continue
            # -meta / -meta.all request headers ONLY, even with -out.max > 0.
            # Normal VOTable data replies already include FIELD descriptions.
            params = {'-source': tid, '-out.all': '1', '-out.max': '100000'}
            candidates.append({'url': 'https://vizier.cds.unistra.fr/viz-bin/votable?' + urlencode(params),
                'format': 'votable', 'vizier_export': params,
                'association': {'rule_id': 'cds-resource-primary-publication-export-1',
                    'parent_bibcodes': [cited], 'catalog_id': catalog, 'source_table_id': tid,
                    'discovery_artifact_ref': artifact_ref,
                    'discovery_sha256': hashlib.sha256(raw).hexdigest(),
                    'dataset_citation': info.get('citation'), 'landing_url': info.get('reference_url'),
                    'locator': 'RESOURCE/INFO[name=cites] Article or Data origin sources',
                    'representation': 'official_vizier_export',
                    'native_file_claimed': False}})
    return candidates


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
