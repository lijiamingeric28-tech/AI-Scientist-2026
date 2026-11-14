"""Local citation and exact-coordinate checks; no second explanation model."""
from decimal import Decimal, InvalidOperation
from copy import deepcopy
import re

from astroquery_ai.runtime.errors import DomainError


def validate_units(response, units):
    if not isinstance(response, dict) or set(response) != {'units'} or not isinstance(response['units'], list):
        raise DomainError('INSIGHT_RESPONSE_SCHEMA', '解释响应不完整')
    by_id = {u['unit_id']: u for u in units}
    if any(not isinstance(u, dict) or not isinstance(u.get('unit_id'), str) for u in response['units']):
        raise DomainError('INSIGHT_RESPONSE_SCHEMA', '解释单元格式无效')
    if len(response['units']) != len(units) or {u.get('unit_id') for u in response['units']} != set(by_id):
        raise DomainError('INSIGHT_UNIT_MISMATCH', '解释单元范围不一致')
    validated = []
    for proposed in response['units']:
        current = by_id[proposed['unit_id']]
        records = {r['measurement_id']: r for r in current['measurements']}
        claims = {c['claim']['claim_id'] for c in current['claims']}
        controlled = proposed.get('numeric_mode') == 'snapshot_placeholders/1'
        paragraphs = deepcopy(proposed.get('paragraphs'))
        numeric_issues=[]
        if not isinstance(paragraphs, list) or not 1 <= len(paragraphs) <= 12:
            raise DomainError('INSIGHT_PARAGRAPHS_MISSING', '解释缺少段落')
        for paragraph_index, p in enumerate(paragraphs):
            if (not isinstance(p, dict) or set(p) - {'text', 'kind', 'measurement_ids', 'claim_ids', 'value_assertions'}
                    or not isinstance(p.get('text'), str) or not p['text'].strip()
                    or p.get('kind') not in {'source_fact', 'property_definition', 'theory_background', 'usage_limit'}
                    or not all(isinstance(p.get(k), list) and all(isinstance(v, str) for v in p[k]) for k in ('measurement_ids', 'claim_ids'))):
                raise DomainError('INSIGHT_PARAGRAPH_SCHEMA', '解释段落协议无效',
                    unit_id=current['unit_id'], paragraph_index=paragraph_index,
                    unexpected_paragraph_fields=sorted(set(p) - {'text', 'kind', 'measurement_ids', 'claim_ids', 'value_assertions'})
                        if isinstance(p, dict) else [],
                    repair_hint='误差component_id/value_key/value/unit属于value_assertions[]中的坐标声明，不是段落顶层字段。保留正文和原报分量，不生成新值。')
            if set(p['measurement_ids']) - records.keys() or set(p['claim_ids']) - claims:
                raise DomainError('INSIGHT_UNSUPPORTED_CITATION', '解释引用不属于该单元')
            if (p['kind'] == 'source_fact' and not p['measurement_ids']
                    or p['kind'] == 'theory_background' and not p['claim_ids']):
                raise DomainError('INSIGHT_UNSUPPORTED_CLAIM', '解释缺少对应依据')
            assertions = p.get('value_assertions', [])
            if not isinstance(assertions, list):
                raise DomainError('INSIGHT_VALUE_SCHEMA', '数值声明格式无效')
            template = p['text']
            if controlled and assertions:
                indices=list(dict.fromkeys(int(n) for n in re.findall(r'\{\{v(\d+)\}\}',template)))
                if (len(indices)==len(assertions) and indices and indices[0]>0
                        and indices==list(range(indices[0],indices[0]+len(indices)))):
                    # A coherent running index is just a label offset. Bind
                    # the same ordered assertions locally; never reorder them
                    # or infer a missing measurement/component/coordinate.
                    p['original_text_template']=template
                    offset=indices[0]
                    template=re.sub(r'\{\{v(\d+)\}\}',lambda m:'{{v'+str(int(m[1])-offset)+'}}',template)
                    p['text']=template
            for assertion_index, assertion in enumerate(assertions):
                if not isinstance(assertion, dict):
                    raise DomainError('INSIGHT_VALUE_SCHEMA', '数值引用必须是坐标对象')
                record = records.get(assertion.get('measurement_id'))
                coordinate = assertion.get('coordinate')
                if not record or record['measurement_id'] not in p['measurement_ids'] or coordinate not in {'source', 'processed','context'}:
                    raise DomainError('INSIGHT_VALUE_SCOPE', '数值声明越过本单元测量')
                if coordinate=='context':
                    from .insight_inputs import context_quotations
                    anchor=next((e for e in context_quotations(record)
                        if e['evidence_id']==assertion.get('evidence_id')),None)
                    literal=assertion.get('literal')
                    # This is a quotation coordinate, not a new measurement,
                    # unit interpretation or a computation from prose.
                    if (not controlled or not anchor or not isinstance(literal,str)
                            or not literal.strip() or len(literal)>512 or literal not in anchor.get('raw_text','')):
                        raise DomainError('INSIGHT_CONTEXT_SCOPE','上下文引文须逐字来自本记录给定的原文E依据',
                            unit_id=current['unit_id'],paragraph_index=paragraph_index,assertion=assertion)
                    token='{{v'+str(assertion_index)+'}}'
                    if token not in template:
                        raise DomainError('INSIGHT_VALUE_SCOPE','上下文引文缺少对应占位符')
                    if assertion.get('value',literal)!=literal or assertion.get('unit') is not None:
                        raise DomainError('INSIGHT_VALUE_MISMATCH','上下文引文不得自行改字或另加推断单位')
                    assertion.update(value=literal,unit=None,scope='source_context_quotation_not_measurement')
                    if anchor.get('reference_kind'):assertion['reference_kind']=anchor['reference_kind']
                    p['text']=p['text'].replace(token,literal)
                    continue
                value = record['source_value']['value'] if coordinate == 'source' else record['processed_value'].get('value_typed')
                unit = record['source_value'].get('effective_unit', record['source_value']['unit']) if coordinate == 'source' else record['processed_value'].get('coordinate_units', {}).get('target')
                raw_literal = None
                if assertion.get('component_id') is not None:
                    component = next((c for c in record.get('source_uncertainty', {}).get('components', [])
                        if c['component_id'] == assertion['component_id']), None) if coordinate == 'source' else None
                    amplitude = (component.get('values') or {}).get(assertion.get('value_key')) if component else None
                    if component and assertion.get('value_key') == 'raw_text':
                        raw_literal = component.get('raw_text')
                    value = {'kind': 'real', 'value': amplitude} if isinstance(amplitude, str) else None
                    unit = component.get('unit') if component else None
                if controlled:
                    token = '{{v' + str(assertion_index) + '}}'
                    literal = raw_literal if raw_literal is not None else (value or {}).get('value')
                    if not isinstance(literal, str) or token not in template:
                        raise DomainError('INSIGHT_VALUE_SCOPE', '受控数值引用缺少可用快照坐标或占位符')
                    if ('value' in assertion and assertion['value'] != literal
                            or 'unit' in assertion and assertion['unit'] != unit):
                        raise DomainError('INSIGHT_VALUE_MISMATCH', '受控数值引用不得改写快照')
                    assertion.update(value=literal, unit=unit)
                    symbol = unit.get('canonical_symbol') if isinstance(unit, dict) else unit
                    rendered=literal + (' ' + symbol if symbol else '')
                    if assertion.get('component_id') is None:
                        representation=record['source_value'].get('representation') if coordinate=='source' else record['processed_value'].get('representation')
                        kind=representation.get('kind') if isinstance(representation,dict) else representation
                        if kind in {'log10','ln'} and symbol!='dex':
                            # The unit is a reference basis of this coordinate,
                            # not a physical unit multiplying its coefficient.
                            rendered=literal+'（'+kind+'坐标'+('，参考单位'+symbol if symbol and symbol!='1' else '')+'）'
                    p['text'] = p['text'].replace(token, rendered)
                if raw_literal is not None:
                    equal = isinstance(raw_literal, str) and assertion.get('value') == raw_literal
                else:
                    try:
                        equal = value and value.get('kind') in {'real', 'integer'} and Decimal(str(assertion['value'])) == Decimal(value['value'])
                    except (InvalidOperation, KeyError, TypeError):
                        equal = False
                if not equal or assertion.get('unit') != unit:
                    raise DomainError('INSIGHT_VALUE_MISMATCH', '解释数值或单位与封口快照不符',
                        unit_id=current['unit_id'], paragraph_index=paragraph_index, assertion=assertion,
                        repair_hint='主值绑定source/processed坐标；误差value_key只能选该分量values已有键，或用raw_text逐字引用原误差栏。原报未解语义保持未知，不能用列名当values键，不生成新幅度或置信度。')
                if controlled:
                    continue  # Coordinate proof and rendering replace prose-number matching.
                bound_text = '\n'.join(q['text'] for q in paragraphs if record['measurement_id'] in q.get('measurement_ids', []))
                if raw_literal is not None:
                    if raw_literal not in bound_text:
                        raise DomainError('INSIGHT_VALUE_TEXT_MISMATCH', '解释未逐字引用所声明的误差原文',
                            unit_id=current['unit_id'], paragraph_index=paragraph_index, unused_assertion=assertion)
                    continue  # Literal citation grants no numeric error interpretation.
                tokens = re.findall(r'(?<![\d.])[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', bound_text)
                if not any(Decimal(t) == Decimal(str(assertion['value'])) for t in tokens):
                    raise DomainError('INSIGHT_VALUE_TEXT_MISMATCH', '解释文字未包含其数值声明',
                        unit_id=current['unit_id'], paragraph_index=paragraph_index,
                        unused_assertion=assertion,
                        repair_hint='该声明坐标已与快照核对，但正文未写这个数。只声明正文实际叙述的坐标；删去多余声明，或在正文准确说明该已有坐标，不改源值和处理值、不另作换算。')
            # Numeric source statements must expose a checkable native/processed
            # coordinate. Theory constants and definitions use different kinds.
            if controlled:
                if re.search(r'\{\{.*?\}\}', p['text']):
                    raise DomainError('INSIGHT_VALUE_SCOPE', '解释含有未绑定快照字段的占位符')
                # Coordinates are the protocol's proof. This secondary guard
                # prevents a generated measurement decimal from bypassing it
                # just by setting numeric_mode and omitting all references.
                unbound = re.sub(r'\{\{v\d+\}\}', '', template)
                unbound_numbers=re.findall(r'(?<![\dA-Za-z_.])(?:\d+\.\d+|\.\d+|\d+[eE][+-]?\d+)', unbound)
                if p['kind'] in {'source_fact', 'usage_limit'} and unbound_numbers:
                    numeric_issues.append({'paragraph_index':paragraph_index,'unbound_literals':unbound_numbers})
                p['text_template'] = template
                p['numeric_mode'] = 'snapshot_placeholders/1'
            elif p['kind'] == 'source_fact' and re.search(r'\d+\.\d+', p['text']) and not assertions:
                raise DomainError('INSIGHT_VALUE_ASSERTION_MISSING', '数值事实缺少可核验坐标')
        if numeric_issues:
            raise DomainError('INSIGHT_VALUE_ASSERTION_MISSING','事实数字须绑定快照主值/误差或本记录原文上下文引文',
                unit_id=current['unit_id'],paragraph_index=numeric_issues[0]['paragraph_index'],paragraph_issues=numeric_issues,
                unbound_literals=list(dict.fromkeys(n for issue in numeric_issues for n in issue['unbound_literals'])),
                repair_hint='一次修正所有列出的段落；只选已有快照坐标或本记录实际原文/方法引文，不补猜数字。')
        covered = {mid for p in paragraphs for mid in p['measurement_ids']}
        if not controlled and records.keys() - covered:
            raise DomainError('INSIGHT_MEASUREMENT_COVERAGE', '当前单元有测量未得到解释或限制说明')
        if not controlled and claims and not any(p['kind'] == 'theory_background' and p['claim_ids'] for p in paragraphs):
            raise DomainError('INSIGHT_THEORY_MISSING', '已提供适用理论但解释未引用')
        validated.append((current, paragraphs))
    return validated


def explanation_coverage(unit):
    """Mentioned is a display scope, never a claim of independent checking."""
    available = [m['measurement_id'] for m in unit['measurements']]
    mentioned = sorted({mid for p in unit['paragraphs'] for mid in p.get('measurement_ids', [])})
    return {'scope': 'group_background', 'available_measurement_ids': available,
            'mentioned_measurement_ids': mentioned,
            'not_individually_discussed': [mid for mid in available if mid not in mentioned],
            'claim_ids_used': sorted({cid for p in unit['paragraphs'] for cid in p.get('claim_ids', [])}),
            'individual_scientific_audit': False}


def basic_explanation(unit, spec):
    """Truthful deterministic delivery after the bounded model attempts."""
    binding = next(b for b in spec['properties'] if b['property_id'] == unit['property_id'])
    mids = [m['measurement_id'] for m in unit['measurements']]
    text = (binding['definition']['name_cn'] + '：已保留本组' + str(len(mids))
            + '条测量。原报、有效处理值、各误差及条件请查看同一快照的数据详情。'
            if mids else binding['definition']['name_cn'] + '：适用知识及条件保留在知识卡片中。')
    return [{'text': text + '扩展解释未完成。', 'kind': 'source_fact' if mids else 'usage_limit',
             'measurement_ids': mids, 'claim_ids': [], 'value_assertions': []}]
