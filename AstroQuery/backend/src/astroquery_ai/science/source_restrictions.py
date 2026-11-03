'Bind source-restriction assessments to inspected material and one measurement.'

from astroquery_ai.runtime.codec import digest, canonical

from astroquery_ai.science.measurements.admission_contracts import normalized

def catalog_source_materials(source, column_names=None):
    """Stable IDs for actual saved columns/ReadMe text, never invented paths."""
    metadata = source.get('metadata', {})
    columns = [c for c in metadata.get('columns', []) if column_names is None or c['name'] in column_names]
    texts = {'column:' + c['name']: canonical(c).decode() for c in columns}
    parsed = (metadata.get('catalog_document') or {}).get('parsed', {})
    for group in ('fields', 'notes'):
        for key, snippets in parsed.get(group, {}).items():
            if group == 'fields' and column_names is not None and (key not in column_names):
                continue
            for index, snippet in enumerate(snippets):
                texts[f'readme-{group}:{key}:{index}'] = snippet['text']
    for key in ('catalog_scope', 'file_header'):
        if isinstance(parsed.get(key), dict) and parsed[key].get('text'):
            texts['readme-' + key] = parsed[key]['text']
    return texts

def catalog_information_prompt(target, info_index, items):
    """The same evidence-only restriction check for normal M03 and regression."""
    from .source_review import SourceInformationSelections
    schema = SourceInformationSelections.model_json_schema()
    aliases = {f's{n + 1}': {'material_id': key, 'text': text} for n, (key, text) in enumerate(info_index.items())}
    for key in ('checked_ids', 'caution_ids'):
        schema['$defs']['SourceInformationSelection']['properties'][key]['items'] = {'enum': list(aliases)}
    return {'instruction': '独立核对候选采用限制及证据定位，不盲从前一次source_quality，不改任何值、误差或条件。返回完整JSON对象items，每项只有item_id、state、checked_ids、caution_ids、note。checked_ids选择source_information_index的短键s1、s2等，不拼接:description或说明文字。state=checked必须至少选择真正检查过的键；未查或不能判断用unresolved。caution_ids仅选确实适用于本条实际数值的来源限制，note解释适用依据。普通字段定义、Mean error标签、空值编码约定（如?=0）本身不说明本行有坏质量；须结合给定原误差栏确认是否实际适用。可选误差角色/置信度、时标或带宽未报，不等于已知来源不可靠。普通引用、一般方法、其他量的注释不扣采用分；确实的低估、污染等适用限制应保留。', 'id_rule': 'checked_ids和caution_ids只选source_information_index的短键s1、s2等；禁止返回冒号、引文、拼接路径或material_id。', 'schema': schema, 'target': target, 'source_information_index': aliases, 'items': items}

def decode_catalog_information(response, payload):
    from .source_review import SourceInformationSelections
    from astroquery_ai.runtime.errors import DomainError
    checked = SourceInformationSelections.model_validate(response)
    aliases = payload['source_information_index']
    result = []
    for item in checked.items:
        if any((key not in aliases for key in [*item.checked_ids, *item.caution_ids])):
            raise DomainError('SOURCE_INFO_SCOPE', '来源检查必须选择实际材料短键')
        result.append(item.model_copy(update={k: [aliases[key]['material_id'] for key in getattr(item, k)] for k in ('checked_ids', 'caution_ids')}))
    return checked.model_copy(update={'items': result})

def checked_source_information(info, texts, *, measurement_id, measurement_version, evidence_refs, interpretation_ref, check_basis=None):
    document = info.model_dump(mode='json') if hasattr(info, 'model_dump') else info
    context_index = texts if isinstance(texts, dict) else {}
    material = [normalized(t) for t in (context_index.values() if context_index else texts) if isinstance(t, str) and t.strip()]

    def resolve(quote):
        if not isinstance(quote,str):return quote
        if quote in context_index:return context_index[quote]
        for key,text in context_index.items():
            if quote.startswith(key+':'):
                excerpt=quote[len(key)+1:].strip()
                if len(excerpt)>=12 and normalized(excerpt) in normalized(text):
                    return text
        return quote

    def grounded(quote):
        if context_index and quote not in context_index and (not isinstance(quote, str) or len(quote.strip()) < 12 or (not any((c.isalnum() for c in quote)))):
            return False
        quote = resolve(quote)
        return isinstance(quote, str) and bool(quote.strip()) and any((normalized(quote) in t for t in material))
    raw = (document or {}).get('raw_info', [])
    cautions = (document or {}).get('caution_quotes', [])
    valid = bool(document and document['state'] == 'checked' and raw and all((grounded(q) for q in [*raw, *cautions])))
    result = {'measurement_id': measurement_id, 'measurement_version': measurement_version, 'state': 'checked' if valid else 'unresolved' if document else 'not_checked', 'information': document, 'scope': 'saved_source_information_only', 'interpretation_ref': interpretation_ref, 'evidence_refs': evidence_refs, 'inspected_quotes': [resolve(q) for q in raw] if valid else [], 'check_basis': check_basis, 'cautions': []}
    if valid:
        for quote in cautions:
            quote = resolve(quote)
            result['cautions'].append({'issue_key': 'source-caution-' + digest([measurement_id, quote]), 'rule_id': 'explicit_source_restriction', 'category': 'source_caution', 'measurement_ids': [measurement_id], 'state': 'open', 'message': quote, 'evidence_refs': evidence_refs, 'level': 50, 'impact': {'dimension': 'adoption', 'level': 50, 'reason': 'explicit_source_restriction'}})
    result['check_id'] = 'source-check-' + digest(result)
    return result
