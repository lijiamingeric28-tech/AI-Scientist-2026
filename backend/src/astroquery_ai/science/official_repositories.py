"""Versioned author deposits explicitly linked by an acquired publication."""
import hashlib
import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit, quote
from .attachments import FORMATS, CONTAINERS
from .literature import normalize_doi


async def repository_request(fetch,url,*,maximum_attempts=3,**kwargs):
    """Retry only transient failures of the same authorized deposit endpoint."""
    import asyncio
    from astroquery_ai.runtime.errors import DomainError
    if type(maximum_attempts) is not int or not 1<=maximum_attempts<=3:
        raise ValueError('Repository retries must be within 1..3')
    failures=[]
    for index in range(maximum_attempts):
        try:
            raw,metadata=await fetch(url,**kwargs)
            return raw,{**metadata,'repository_prior_failures':failures,
                        'repository_request_count':index+1}
        except DomainError as exc:
            transient=exc.code in {'SOURCE_HTTP_TIMEOUT','SOURCE_TRANSPORT_ERROR'} or (
                exc.code=='SOURCE_HTTP_ERROR' and isinstance(exc.details.get('provider_status'),int)
                and exc.details['provider_status']>=500)
            if not transient:raise
            failures.append({'url':url,'attempt':index+1,'reason':exc.code})
            if index+1==maximum_attempts:
                raise DomainError('OFFICIAL_REPOSITORY_UNAVAILABLE','作者数据仓库有限重试后仍不可用',502,
                    attempts=failures,last_error=exc.code) from exc
            await asyncio.sleep((.5,1.5)[min(index,1)])


def paper_zenodo_links(index):
    seen, found = set(), []
    for page in index.get('pages', []):
        text = page.get('text','')
        for match in re.finditer(r'https?://(?:www\.)?zenodo\.org/(?:records?|record)/([0-9]+)', text):
            identifier = match[1]
            if identifier in seen:
                continue
            seen.add(identifier)
            found.append({'record_id':identifier,'url':'https://zenodo.org/records/'+identifier,
                'page':page['page'],'quote':text[max(0,match.start()-160):match.end()+160]})
    return found


def zenodo_files(document, expected_dois, locator, *, metadata_artifact):
    metadata = document.get('metadata',{})
    expected = {normalize_doi(x) for x in expected_dois}
    relations=[]
    for relation in metadata.get('related_identifiers',[]):
        if relation.get('scheme')!='doi' or relation.get('relation') not in {'isPartOf','isSupplementTo','isDerivedFrom'}:
            continue
        try:
            doi=normalize_doi(relation['identifier'])
        except (ValueError,KeyError):
            continue
        if doi in expected:
            relations.append({**relation,'normalized_doi':doi})
    if not relations:
        return []
    record_id=str(document.get('id',''))
    if not record_id.isdecimal():
        return []
    candidates=[]
    for file in document.get('files',[]):
        name=file.get('key','');url=file.get('links',{}).get('self','')
        parts=urlsplit(url)
        if parts.scheme!='https' or parts.hostname!='zenodo.org' or not parts.path.startswith('/api/records/'+record_id+'/files/'):
            continue
        suffix=PurePosixPath(name).suffix.lower()
        fmt='container' if suffix in CONTAINERS else FORMATS.get(suffix)
        if not fmt:
            continue
        candidates.append({'url':url,'format':fmt,'filename':name,'repository_checksum':file.get('checksum'),
            'association':{'rule_id':'publication-linked-deposit-related-doi-1',
              'parent_dois':[r['normalized_doi'] for r in relations],
              'record_id':record_id,'record_doi':document.get('doi') or metadata.get('doi'),
              'record_version':metadata.get('version'),'related_identifiers':relations,
              'repository_metadata_artifact_ref':metadata_artifact,
              'publication_locator':locator,'declared_filename':name}})
    return candidates


def verify_repository_checksum(raw, candidate):
    value=candidate.get('repository_checksum')
    if not value:
        return
    algorithm,sep,expected=value.partition(':')
    if not sep or algorithm not in {'md5','sha256'}:
        return
    if hashlib.new(algorithm,raw).hexdigest()!=expected.lower():
        from astroquery_ai.runtime.errors import DomainError
        raise DomainError('REPOSITORY_FILE_CHECKSUM','作者仓库文件与所选版本公布的校验和不一致')
