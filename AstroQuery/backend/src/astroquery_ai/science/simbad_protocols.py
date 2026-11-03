"""Source-preserving SIMBAD Sesame adapter; never a coordinate-only resolver."""
import re
import unicodedata
import xml.etree.ElementTree as ET

from astroquery_ai.runtime.errors import DomainError


def _name(value):
    return ''.join(unicodedata.normalize('NFKC', value).casefold().split()).replace('−','-').replace('–','-')


def variable_star_name_form(identifier, mention):
    """SIMBAD V* is a naming-system prefix, not a component or arbitrary alias.

    Only the complete native variable designation may omit that prefix. Its
    remaining letters/number, constellation and any component stay significant.
    """
    match = re.fullmatch(r'V\*\s+((?:[A-Za-z]{1,2}|V\d+)\s+[A-Za-z]{3})', identifier.strip())
    return bool(match and _name(match[1]) == _name(mention))


def sesame_view(raw, mention):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise DomainError('IDENTITY_PROVIDER_SCHEMA','身份响应不得包含外部声明')
    try:root=ET.fromstring(raw)
    except ET.ParseError as exc:raise DomainError('IDENTITY_PROVIDER_SCHEMA','Sesame身份响应不是有效XML') from exc
    if root.tag!='Sesame' or len(root.findall('Target'))!=1:
        raise DomainError('IDENTITY_PROVIDER_SCHEMA','Sesame身份范围无效')
    target=root.find('Target');resolvers=target.findall('Resolver')
    if _name(target.findtext('name','')) != _name(mention):
        raise DomainError('IDENTITY_PROVIDER_SCHEMA','Sesame请求名与当前请求不一致')
    rows,native=[],[]
    for resolver in resolvers:
        authority=resolver.get('name','')
        if authority.partition('=')[0] not in {'S','Sca'} or 'Simbad' not in authority:
            raise DomainError('IDENTITY_AUTHORITY_MISMATCH','备用身份结果没有明确的SIMBAD来源')
        if any('from cache' in (n.text or '').lower() for n in resolver.findall('INFO')):
            raise DomainError('IDENTITY_CACHED_RESULT','本次要求实时SIMBAD核对，不能静默采用服务器缓存')
        oid=resolver.findtext('oid','').lstrip('@');main=resolver.findtext('oname','').strip()
        otype=resolver.findtext('otype','').strip();aliases=[n.text.strip() for n in resolver.findall('alias') if n.text and n.text.strip()]
        if not re.fullmatch(r'[0-9]{1,40}',oid) or not main or not otype:
            raise DomainError('IDENTITY_PROVIDER_SCHEMA','SIMBAD备用响应缺少对象编号、主名或类型')
        normalized_name = next((v for v in [main,*aliases] if variable_star_name_form(v,mention)),None)
        if _name(mention) not in {_name(v) for v in [main,*aliases]} and normalized_name is None:
            raise DomainError('IDENTITY_ALIAS_MISMATCH','请求名不在SIMBAD实际返回的主名/别名中')
        def number(key):
            value=resolver.findtext(key)
            if value is None:return None
            try:return float(value)
            except ValueError as exc:raise DomainError('IDENTITY_PROVIDER_SCHEMA','SIMBAD备用坐标不是数值') from exc
        # Keep raw aliases below; carry the evidenced syntax form for ordinary
        # row matching and paper subject links, never a guessed object alias.
        rows.append([oid,main,otype,number('jradeg'),number('jdedeg'),'|'.join([*aliases,*([mention] if normalized_name else [])])])
        native.append({'oid':oid,'resolver':authority,'native_xml_fields':[
            {'path':parent.tag+'/'+child.tag,'text':child.text,'attributes':dict(child.attrib)}
            for parent in resolver.iter() for child in parent if child.text and child.text.strip()],
            **({'identifier_normalization':{'source_identifier':normalized_name,'submitted_name':mention,
                'rule':'SIMBAD_variable_designation_optional_Vstar_prefix'}} if normalized_name else {})})
    return {'metadata':[{'name':n,**({'unit':'deg'} if n in {'ra','dec'} else {})}
                        for n in ('oid','main_id','otype','ra','dec','ids')],
            'data':rows,'native_records':native}
