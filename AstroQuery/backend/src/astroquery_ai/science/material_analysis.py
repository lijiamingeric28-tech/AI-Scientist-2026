"""Strict, read-only supplement over a material/property or property-wide scope."""
from copy import deepcopy
import json

from astroquery_ai.application.material_workbench import MaterialIndex
from astroquery_ai.runtime.errors import DomainError
from . import author_insights, property_insights, task_knowledge
from .insight_inputs import measurement_input, explanation_wire

SCHEMA = 'MaterialAnalysis/1'
MODEL_VERSION = property_insights.PROTOCOL
# The installed M11 scientific receipt covers this exact output ceiling.
OUTPUT_LIMIT = 4096
INPUT_PROTOCOL = 'material-reading-input/2'
VALIDATION_POLICY = 'reading-evidence-tiers/1'


def recover_json_fields(raw):
    """Recover complete JSON fields/items only; never complete scientific text."""
    text = raw.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
    decoder = json.JSONDecoder(strict=False)
    try:
        value = decoder.decode(text)
        if isinstance(value, dict):
            return value
    except (ValueError, TypeError):
        pass
    if not text.startswith('{'):
        return {}
    result, pos = {}, 1
    while pos < len(text):
        while pos < len(text) and text[pos] in ' \t\r\n,': pos += 1
        try:
            key, pos = decoder.raw_decode(text, pos)
            if not isinstance(key, str): break
            while pos < len(text) and text[pos].isspace(): pos += 1
            if text[pos:pos+1] != ':': break
            pos += 1
            while pos < len(text) and text[pos].isspace(): pos += 1
            start = pos
            value, pos = decoder.raw_decode(text, pos)
            result[key] = value
        except ValueError:
            if 'start' in locals() and text[start:start+1] == '[':
                values, cursor = [], start + 1
                while cursor < len(text):
                    while cursor < len(text) and text[cursor] in ' \t\r\n,': cursor += 1
                    try: value, cursor = decoder.raw_decode(text, cursor)
                    except ValueError: break
                    values.append(value)
                if values: result[key] = values
            break
    return result


def usable(card):
    # Completed reading is not scientific adoption. Rejected citations remain
    # warnings/unverified notes; usable sibling paragraphs are never discarded.
    return bool(card and card.get('sections', {}).get('found'))


def _reading_response(response):
    if not isinstance(response, dict):
        raise DomainError('INSIGHT_CARD_SCHEMA', '解读需包含可读取的结构')
    result = deepcopy(response)
    for key in ('analysis', 'material_analysis', 'result', 'data', 'report'):
        nested = result.get(key)
        if isinstance(nested, dict) and any(name in nested for name in ('found', 'observations', 'comparison', 'uses')):
            result = nested
            break
    aliases = {'found': ('observations', 'source_observations'), 'comparison': ('methods', 'methodology'),
               'uses': ('interpretation', 'applications'), 'limitations': ('boundaries', 'caveats')}
    for key, alternatives in aliases.items():
        if key not in result:
            result[key] = next((result[name] for name in alternatives if name in result), [])
        if isinstance(result[key], dict): result[key] = [result[key]]
        if result[key] is None: result[key] = []
    result.setdefault('findings', [])
    if result['findings'] is None: result['findings'] = []
    return result


def scope_unit(body, spec, context, material_id, property_id, kind):
    if kind not in {'material', 'property_comparison'}:
        raise DomainError('MATERIAL_ANALYSIS_SCOPE', '解读范围必须为本资料或同性质对照', 422)
    index = MaterialIndex(body)
    if kind == 'property_comparison' and material_id is None:
        group, pid = None, property_id
    else:
        group, pid = index.resolve(material_id, property_id)
    if pid is None:
        raise DomainError('MATERIAL_ANALYSIS_PROPERTY', '请选择已确认的性质', 422)
    if pid not in index.names:
        raise DomainError('MATERIAL_ANALYSIS_PROPERTY', '当前结果没有此性质', 422)
    ids = set(index.record_ids(group, pid)) if group else set()
    records = [r for r in body['measurements'] if r['property_ref']['id'] == pid
               and (kind == 'property_comparison' or r['measurement_id'] in ids)]
    current = author_insights.unit(body, pid, [measurement_input(body, r) for r in records],
                                   task_knowledge.blocks(context, pid))
    return current, group


def _formula(claim):
    raw = claim.get('raw_entry') or {}
    value = claim.get('formula') or raw.get('formula') or raw.get('equation')
    return value if isinstance(value, str) else None


def validate_supplement(response, current, bindings=None):
    # The existing calibrated reply parser validates the four sections and M/E/K
    # ownership. Supplement recommendations have stricter provenance requirements.
    response = _reading_response(response)
    loose = []
    for section in property_insights.SECTIONS:
        if isinstance(response[section], str):
            loose.append({'section': section, 'text': response[section], 'verification': 'needs_review', 'usable_as_measurement': False})
            response[section] = []
    card = property_insights.validate_reply(response, current, bindings)
    card['unverified_advice'] = loose
    own = response.get('recommendations') or {}
    if not isinstance(own, dict):
        if isinstance(own, str): card['unverified_advice'].append({'section': 'recommendations', 'text': own, 'verification': 'needs_review', 'usable_as_measurement': False})
        own = {}
    result = {}
    records = {r['measurement_id']: r for r in current['measurements']}
    claims = {c['claim']['claim_id']: c for c in current['claims']}

    def checked(item, text):
        from .insight_inputs import context_quotations
        # Expand one recommendation at a time. A rejected sibling must never
        # erase valid advice or silently become a complete cached result.
        fields = ('measurement_ids', 'evidence_ids', 'claim_ids')
        explicit = {}
        for key in fields:
            value = item.get(key, item.get(key.removesuffix('s'), []))
            explicit[key] = [value] if isinstance(value, str) else [] if value is None else value
        item = explanation_wire(explicit, bindings, expand=True) if bindings else deepcopy(explicit)
        if any(not isinstance(item.get(key), list) or any(not isinstance(value, str) for value in item[key]) for key in fields):
            raise DomainError('MATERIAL_ANALYSIS_REFERENCE', '建议必须显式提供准确引用数组')
        if not any(item[key] for key in fields):
            raise DomainError('MATERIAL_ANALYSIS_REFERENCE', '建议没有可核对依据')
        mids, eids = set(item['measurement_ids']), set(item['evidence_ids'])
        if mids - records.keys():
            raise DomainError('MATERIAL_ANALYSIS_REFERENCE', '建议引用越过当前范围')
        if mids and eids - {e['evidence_id'] for mid in mids for e in context_quotations(records[mid])}:
            raise DomainError('MATERIAL_ANALYSIS_REFERENCE', '建议原文不属于明确指向的测量')
        refs = property_insights._entry({'text': str(text or ''), **{key: item[key] for key in fields}},
                                        current, None, section='uses')
        if set(refs['measurement_ids']) != mids:
            raise DomainError('MATERIAL_ANALYSIS_REFERENCE', '建议不得扩展受影响测量范围')
        return refs

    def require_own_evidence(refs):
        from .insight_inputs import context_quotations
        if any(not set(refs['evidence_ids']).intersection(e['evidence_id'] for e in context_quotations(records[mid]))
               for mid in refs['measurement_ids']):
            raise DomainError('MATERIAL_ANALYSIS_REFERENCE', '每条建议目标必须有自身原文依据')

    def reject(field, exc, item):
        card['validation_issues'].append({'section': field, 'code': getattr(exc, 'code', 'MATERIAL_ANALYSIS_REFERENCE'), 'severity': 'warning'})
        if isinstance(item, dict):
            text = next((item[key] for key in ('rationale','guidance','reason','text') if isinstance(item.get(key), str) and item[key].strip()), None)
            if text:
                card['unverified_advice'].append({'section': field, 'text': text, 'verification': 'needs_review', 'usable_as_measurement': False})

    benchmark = own.get('benchmark')
    if isinstance(benchmark, dict):
        try:
            refs = checked(benchmark, benchmark.get('reason') or benchmark.get('text'))
            ids = refs['measurement_ids']
            if len(ids) != 1 or not refs['evidence_ids']:
                raise DomainError('MATERIAL_ANALYSIS_BENCHMARK', '参考值必须绑定一条真实测量及原文')
            require_own_evidence(refs)
            record = records[ids[0]]
            result['benchmark'] = {**refs, 'measurement_id': ids[0],
                'source_value': deepcopy(record['source_value']),
                'source_uncertainty': deepcopy(record['source_uncertainty']),
                'source': deepcopy(record['source']), 'conditions': deepcopy(record.get('conditions', [])),
                'confidence_level': benchmark.get('confidence_level') if benchmark.get('confidence_level') in {'high', 'medium', 'conditional'} else 'not_assessed',
                'assessment_kind': 'model_suggestion_not_scientific_adoption'}
        except (DomainError, KeyError, TypeError) as exc:
            reject('benchmark', exc, benchmark)
    for field, text_field in (('data_cleaning', 'rationale'), ('application_guidance', 'guidance')):
        result[field] = []
        for item in own.get(field, []) if isinstance(own.get(field), list) else []:
            try:
                if not isinstance(item, dict):
                    raise DomainError('MATERIAL_ANALYSIS_REFERENCE', '建议必须提供准确引用')
                refs = checked(item, item.get(text_field) or item.get('text') or item.get('reason'))
                if not refs['measurement_ids'] and not refs['evidence_ids'] and not refs['claim_ids']:
                    raise DomainError('MATERIAL_ANALYSIS_REFERENCE', '建议没有可核对依据')
                if field == 'data_cleaning' and (not refs['measurement_ids'] or not refs['evidence_ids']
                        or item.get('action_type') not in {'exclude', 'deprioritize', 'transform'}):
                    raise DomainError('MATERIAL_ANALYSIS_REFERENCE', '筛选建议须绑定记录及原文')
                if field == 'data_cleaning':
                    require_own_evidence(refs)
                entry = {**refs, **{key: str(item.get(key) or '') for key in
                    ('rule', 'action', 'action_type', 'scenario')}, 'suggestion_only': True}
                supported = [claims[cid] for cid in refs['claim_ids'] if cid in claims]
                formula = next((_formula(c) for c in supported if _formula(c)), None)
                if formula:
                    entry.update(formula=formula, formula_claim_id=next(c['claim']['claim_id'] for c in supported if _formula(c) == formula))
                result[field].append(entry)
            except (DomainError, KeyError, TypeError) as exc:
                reject(field, exc, item)
    card['recommendations'] = result
    card['scope'] = 'explicit_supplement_records'
    card['validation_policy'] = VALIDATION_POLICY
    card['warnings'] = deepcopy(card['validation_issues'])
    for issue in card['validation_issues']:
        fragment = issue.get('rejected_fragment')
        if isinstance(fragment, dict):
            text = fragment.get('text') or fragment.get('reason')
            if isinstance(text, str) and text.strip():
                card['unverified_advice'].append({'section': issue['section'], 'text': text, 'verification': 'needs_review', 'usable_as_measurement': False})
    return card


def synthesis_reading_input(packed):
    """Compose verified readings, without paying to read the originals twice.

    Every source record has already passed the full batch input and reference
    validation. Keep *all* M/E references, sources, frozen knowledge and batch
    notes. Values and advice in the output are still validated against the full
    original ``current`` unit, never against this reading projection.
    """
    body = property_insights.unpack_materials(packed)
    records = body.get('record_index', [])
    expected = {row['measurement_id'] for row in records}
    coverage = body.get('batch_coverage', [])
    covered = {mid for batch in coverage if batch.get('status') == 'generated' for mid in batch['measurement_ids']}
    if not expected or covered != expected or any(batch.get('status') != 'generated' for batch in coverage):
        raise DomainError('MATERIAL_SYNTHESIS_COVERAGE', '只有完整分批阅读覆盖后才能综合', 409)
    columns = ['measurement_id', 'source_label', 'evidence_ids']
    body['record_index_columns'] = columns
    body['record_index'] = [[row.get(key) for key in columns] for row in records]
    indexed_evidence = {eid for row in records for eid in row.get('evidence_ids', [])}
    body['original_materials'] = {'record_evidence': 'record_index.evidence_ids',
        'additional_evidence_ids': [item['evidence_id'] for item in body.get('original_materials', [])
                                    if item['evidence_id'] not in indexed_evidence]}
    body['input_projection'] = 'verified-batch-synthesis/1'
    body['synthesis_rule'] = (
        '全部记录和原文已由batch_coverage中的生成批次完整阅读。此轮只综合batch_notes里的已校验解释，'
        'record_index按record_index_columns列顺序保存全量引用目录，不是新的测量输入。'
        'original_materials复用该目录的evidence_ids列，额外原文在additional_evidence_ids中。'
        '不得重新推算数值、做统计或增加批内没有支持的发现。'
        '各批曾只含一个来源不代表本范围只有一个来源；以sources和完整覆盖为准，区分批内与跨来源结论。'
        'M/E/K已统一到本轮目录；建议只从batch_notes已引用且有依据的记录中选择，缺少依据时留空。'
        '每条原报数值、误差、条件和出处仍保存于准确交付，程序对输出使用完整封存记录校验。')
    packed = property_insights.pack_materials(body)
    # Reference names are a wire dictionary, not scientific IDs. Short aliases
    # preserve every value while avoiding repeated 64-character dictionary keys.
    aliases = {key: f'R{index}' for index, key in enumerate(packed['shared_materials'])}
    def shorten(value):
        if isinstance(value, dict) and set(value) == {'shared_material_ref'}:
            return {'shared_material_ref': aliases[value['shared_material_ref']]}
        if isinstance(value, dict):
            return {key: shorten(item) for key, item in value.items()}
        if isinstance(value, list):
            return [shorten(item) for item in value]
        return value
    packed['body'] = shorten(packed['body'])
    packed['shared_materials'] = {aliases[key]: value for key, value in packed['shared_materials'].items()}
    return packed


def supplement_input(packed, kind):
    body = property_insights.unpack_materials(packed)
    body['instruction'] = (
        '返回JSON对象，包含found/comparison/uses/limitations/findings五个数组与recommendations对象。'
        '这是独立补充阅读，范围为' + ('当前资料及其明确官方附表' if kind == 'material' else '同一性质全部来源的跨来源对照') +
        '。found描述本范围原文观察，comparison解释方法和条件，uses解释科研用途，limitations明确适用边界。'
        '有真实测量时found至少一条。每个普通条目必须包含text及measurement_ids、evidence_ids、claim_ids三个数组，'
        '只引用record_index、original_materials和knowledge中实际给定的M/E/K标签；未引用的数组填[]。'
        '严格区分原文事实和输入知识，不把其他来源结论写成当前资料发现，不推断未记录的独立性或科学审核状态。'
        'recommendations严格按recommendation_reference_contract返回；没有充分依据时benchmark填null，其他建议填[]。'
        '参考测量只引用恰一条真实测量及该条自身原文，不返回新算数值、recommended_value、公式或默认高可信度。'
        '时序数据按波段/历元/原报条件分别参考，不能强制挑一个总基准。条件未知时明确限制。'
        '筛选建议仅针对明确引用且各有自身原文的记录，不能增加其他目标；行动只是阅读建议，不实际排除、降权或转换。'
        '科研场景必须引用实际测量/原文或已有知识，不补造必要输入、模型、公式或定律。'
        '理论公式由系统从实际引用知识的已有字段读取，不由模型生成。不要输出逐字quote、占位符或长hash。'
        '中文解释，保留准确性质、滤光系统、单位、时间定义与来源差异。')
    refs = {'measurement_ids': '实际M标签的数组', 'evidence_ids': '实际E标签的数组', 'claim_ids': '实际K标签的数组'}
    body['recommendation_reference_contract'] = {
        'benchmark': {'nullable': True, 'fields': {**refs, 'reason': '只在原记录条件内参考的理由'},
            'restriction': '恰一条M且至少一个该条自身E；没有可比较依据时为null。'},
        'data_cleaning': {'array': True, 'fields': {**refs, 'rule': '注意事项', 'action': '建议动作',
            'action_type': 'exclude/deprioritize/transform', 'rationale': '依据与条件限制'},
            'restriction': '每个目标M必须有自身E；不推断额外受影响记录。'},
        'application_guidance': {'array': True, 'fields': {**refs, 'scenario': '科研场景', 'guidance': '已有输入、可开展研究及限制'},
            'restriction': '至少一个实际M/E/K引用；缺口明确说明，不补造公式。'}}
    body['response_example_protocol_only'] = {**{key: [] for key in (*property_insights.SECTIONS, 'findings')},
        'recommendations': {'benchmark': None, 'data_cleaning': [], 'application_guidance': []}}
    return property_insights.pack_materials(body)
