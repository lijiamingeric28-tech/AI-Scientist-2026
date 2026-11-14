'Complete scientific text without duplicating repository provenance in prompts.'

from astroquery_ai.science.measurements.contracts import ExtractionBatch


def confirmed_property_intent(spec,property_id):
    """Carry only wording already mapped and confirmed for this exact binding."""
    selection=spec.get('property_selection') or {}
    return list(dict.fromkeys(r['text'] for r in selection.get('requests',[])
        if property_id in r.get('candidate_property_ids',[]) and isinstance(r.get('text'),str)))

def header_property_view(binding):
    """Column navigation needs physical intent, not execution/audit envelopes.

    Full source rows still pass the unchanged frozen scientific contracts.
    Descriptions and physical distinctions are never truncated.
    """
    definition = binding['definition']
    explanation=definition.get('explanation') or {}
    return {'property_id': binding['property_id'], 'definition': {
        **{k:definition[k] for k in ('name_cn','name_en','quantity_key','quantity_kind','subject_class_id','object_scale_id','value_schema','scope','definition_qualifiers','distinction_notes') if k in definition},
        'description':explanation.get('quantity') or definition['description'],
        **{k:explanation[k] for k in ('subject','representation','evidence_scope') if k in explanation},
        'distinctions':explanation.get('distinctions',[])},
        'stage_contract':'Navigation/retrieval only: use ordinary scientific terminology for this quantity. Source-specific column names are not general literature terms. No numerical derivation or admission granted.'}

def property_view(binding, *, include_output_profile=False):
    keys = ('property_id', 'definition', 'output_profile') if include_output_profile else ('property_id', 'definition')
    view = scientific_view({key: binding[key] for key in keys if key in binding})
    definition=view['definition']
    explanation=definition.get('explanation') or {}
    view['quantity_focus']={k:explanation[k] for k in ('quantity','subject','representation','evidence_scope','distinctions') if k in explanation}
    view['quantity_focus'].update({k:definition[k] for k in ('quantity_kind','scope','definition_qualifiers','distinction_notes') if k in definition})
    view['quantity_focus']['identity_boundary']='The stated quantity_kind describes the SELECTED physical measurand, not merely a dimension or paper topic. Any estimator/model/method explicitly defining the selected quantity is part of its identity: establish what produced this source result, not a method merely cited, compared or used to validate it. Otherwise legitimate method differences remain context, not automatic rejection. Related proxies, offsets and ancillary context are not alternate main values.'
    # Separate scientific identity from legacy source annotations without
    # rewriting or keyword-filtering a scientific sentence. The complete
    # definition remains frozen in the registry and task binding.
    if explanation.get('boundary'):
        boundary=explanation['boundary']
        view['source_annotations']={'original_boundary':boundary,
            'content_kind':'mixed_identity_constraints_and_source_examples',
            'applicability':'This original field can mix general identity/exclusion constraints with source-specific examples. General quantity/estimator/model constraints still apply to new sources. Apply a named source/table convention only to its actual source; do not treat examples as a whitelist or dismiss the entire boundary as source-specific. The model distinguishes these meanings from the complete original text.'}
        explanation.pop('boundary',None)
        # Keep the complete original identity text. Mechanically classifying a
        # mixed boundary as entirely source-specific can drop a main estimator
        # restriction for every new source; the consumer must not do that.
    if not include_output_profile:
        view['stage_contract'] = 'Native source extraction only. Target display coordinates are deliberately absent; normalization occurs later.'
    if binding.get('science_conditions'):
        predicates = {p['key'] for p in binding['science_conditions']['predicates']}
        conditions = {c['key']: dict(c) for c in view['definition']['measurement_conditions_schema'] if c['key'] not in predicates}
        for context in binding['science_conditions']['contexts']:
            conditions[context['key']] = {**conditions.get(context['key'], {}), **{k: context[k] for k in ('key', 'value_type', 'meaning', 'required_scope', 'on_missing') if k in context}}
        view['definition']['measurement_conditions_schema'] = list(conditions.values())
        annotation=view.get('source_annotations',{}).get('original_boundary')
        for context in view['definition']['measurement_conditions_schema']:
            if annotation and context.get('meaning')==annotation:
                # Exact duplicate of the original mixed source annotations,
                # not an independent scientific definition of the main value.
                context.pop('meaning')
                context['meaning_ref']='source_annotations.original_boundary'
        view['source_condition_rule'] = 'Only these context keys, at most once each. Do not output operation predicates or assertions that science gates passed. Unknown remains unknown.'
    return view

def scientific_view(value):
    excluded = {'content_sha256', 'evidence_refs', 'review_ref', 'dependency_refs', 'rule_refs', 'candidate_projection_receipt'}
    if isinstance(value, dict):
        return {key: scientific_view(item) for key, item in value.items() if key not in excluded}
    if isinstance(value, list):
        return [scientific_view(item) for item in value]
    return value

def extraction_schema(*, paper=False):

    def compact(value):
        if isinstance(value, dict):
            return {key: compact(item) for key, item in value.items() if key not in {'title', 'default'}}
        if isinstance(value, list):
            return [compact(item) for item in value]
        return value
    schema = compact(ExtractionBatch.model_json_schema())
    if paper:
        schema['$defs']['MeasurementProposal']['properties'].pop('catalog_field_roles', None)
        schema['$defs'].pop('CatalogFieldRole', None)
    if not paper:
        schema['$defs']['MeasurementProposal']['properties'].pop('local_admission', None)
        schema['$defs']['ErrorProposal']['properties'].pop('semantics_evidence', None)
        for name in ('AdmissionCheck', 'Anchor', 'LocalContext'):
            schema['$defs'].pop(name, None)
        used, pending = (set(), [schema.get('properties', {})])
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                ref = value.get('$ref', '')
                if ref.startswith('#/$defs/') and ref.rsplit('/', 1)[-1] not in used:
                    name = ref.rsplit('/', 1)[-1]
                    used.add(name)
                    pending.append(schema['$defs'][name])
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        schema['$defs'] = {k: v for k, v in schema['$defs'].items() if k in used}
    return schema

def table_view(table, column_names=None):
    """Lossless column metadata matrix; avoids repeating eight JSON keys per field."""
    columns = [column for column in table['columns'] if column_names is None or column['name'] in column_names]
    attributes = sorted({key for column in columns for key in column})
    document = table.get('catalog_document')
    if document:
        from .catalog_document import document_view
        doc_view = document_view(document, {c['name'] for c in columns}, [c['name'] for c in table['columns']])
        doc_view['field_descriptions'] = {name: [{k: v for k, v in span.items() if not (span.get('text') and k in {'description_text', 'unit_token', 'source_format'})} for span in spans] for name, spans in doc_view['field_descriptions'].items()}
    else:
        doc_view = None
    return {'source_quality': '必须检查所给已取得的表头、质量码、脚注、说明与方法限制。每条填写source_quality:{state:checked|unresolved|invalid,raw_info:[实际查过的逐字原文],caution_quotes:[确实适用于此对象和此性质的原文限制],note:检查范围及缺项}。无适用限制可checked且caution_quotes=[]，但raw_info必须是实际检查的来源文字，不填笼统已检查。普通引用、测量方法不同、其他对象或其他量的限制不算本条caution。未读或无法确定适用性为unresolved，不用checked代替。误差可能低估等真实适用限制必须保留；不生成分数。', 'main_value': 'Keep a clearly reported numeric main value numeric even when its optional uncertainty cannot be interpreted. Preserve the error raw and unresolved; do not turn the entire measurement into text.', 'subject_and_role': 'The actual local subject must be the verified target. Other objects in the same paper do not inherit its identity. Initial/trial processing settings are not automatically adopted measurements. Distinguish reported measurements from assumptions; preserve method/fiducial and observation conditions.', **{key: value for key, value in table.items() if key not in {'columns', 'rows', 'source_row_numbers', 'catalog_document', 'readme_context'}}, **({'source_document_context': doc_view} if doc_view else {}), 'column_attributes': attributes, 'columns': [[column.get(key) for key in attributes] for column in columns], 'encoding_note': 'Each columns row follows column_attributes exactly. Null metadata means not supplied, never zero.'}

def proposal_rules(*, catalog=False):
    rules = {'figure_boundary': '禁止采集图内数值，包括图内标题、面板标签、拟合摘要与坐标标注，即使PDF有文字层也一样。图注正文自己写出的数值才属于caption；不能把图内标题改叫caption来准入，图内数值标plot或不输出。', 'quantity_verdict': '星表结果必须明确quantity_match=exact/different/unresolved。已明确是另一物理量时不能一边说明不同一边当目标候选提问；可以不输出该项，或用different并在catalog_quantity_evidence列出实际主值列名，由服务器绑定所给原始列定义。派生投影、变化量、变化率及误差幅度不代替所选主值，同单位不证明同量。确实有待判定的科学解释才用unresolved。正文继续在local_admission.quantity_match给出原文依据。', 'source_quality_scope': '来源检查与量的准入/转换条件分开。原文未报误差置信度、时标、历元或估计器，不等于来源检查未做，也不自动扣采用分。已实际查过表头/脚注且无适用限制，可以checked且caution_quotes=[]，在note保留缺失上下文；未查到或明确限制是否适用不明，才用unresolved。', 'source_quality_binding': 'source_quality.raw_info和caution_quotes优先填写实际提供的原文块ID（例如p4:l1-12），由服务器绑定完整原文，不转抄或缩略。星表可用column:实际列名（例如column:DM），只指所给的实际列元数据。也可给逐字连续引文，但不能加Table header/Row for等自造前缀，不加省略号。raw_info表示实际查过的资料，caution_quotes仅选本条适用限制所在的块/引文。', 'context_scope': '每个local_admission.context必须填写subject_scope=target/all_reported_objects/other/unresolved及property_scope=selected_quantity/all_source_quantities/other/unresolved，逐段查明方法、脚注、误差和限制适用于谁及哪个量。另一对象的局部章节不能因全文也出现目标名而继承；不明则unresolved。条件字段也按同一适用范围填写，不移用邻近对象或其他量的历元/方法。', 'subject_link': '主体名不在数值局部、跨页继承主体、表头省略或别名解释时，给subject_link:{method:evidenced_alias|table_scope|section_scope|cross_page_scope,relation:target|other|unresolved,local_evidence:[Anchor],scope_evidence:[Anchor],counter_evidence:[Anchor],reason:简短连接依据}。local_evidence须指向这处数值的实际局部，scope_evidence说明该局部受哪个对象/表头/章节支配；核对首页及其他对象反证。表格应给table_scope并说明目标行/列与主值的对应，不能因同页含目标列就取其他列的数。目标只出现在比较/引用讨论中，不建立本段归属。不同名字的等价必须有实际交叉标识/表头解释，不能靠模型记忆；程序只核定位，不能把两个名字都出现当作已经等价。直接具名的正文短句可以不填subject_link，但仍核对值属于该主体。', 'source_quality': '必须检查所给已取得的表头、质量码、脚注、说明与方法限制。每条填写source_quality:{state:checked|unresolved|invalid,raw_info:[实际查过的逐字原文],caution_quotes:[确实适用于此对象和此性质的原文限制],note:检查范围及缺项}。无适用限制可checked且caution_quotes=[]，但raw_info必须是实际检查的来源文字，不填笼统已检查。普通引用、测量方法不同、其他对象或其他量的限制不算本条caution。未读或无法确定适用性为unresolved，不用checked代替。误差可能低估等真实适用限制必须保留；不生成分数。', 'native_coordinate': 'Extraction precedes normalization. value.value, unit, representation and every error amplitude MUST describe the native source coordinate, never the requested target coordinate. Copy a plain numeric cell numerically unchanged, retaining raw_value verbatim. A source multiplier such as 10^-9 belongs in source_unit, never pre-multiply the coefficient. Output profile and conversion policies describe later processing only. Unknown optional comparison/receiver/confidence context does not make an otherwise identified main value ambiguous; retain that context unknown separately.', 'catalog_error_semantics': '星表误差若主张role/statistical meaning/level，必须在catalog_semantics_evidence中给出实际误差列column、列description里的逐字quote和aspect=role/meaning/level。仅写uncertainty/error、including systematic、per catalog convention，不证明标准差或1sigma。不明则meaning=reported_error、role=unspecified、level_kind=null。保留列计划中的correlation/covariance；轴或依赖不清时单独原样保留且unresolved，不能悄悄省略或假定独立。', 'uncertainty_semantics': '误差角色stat/sys/total、标准差/置信区间含义和置信水平必须由原文直接说明，并给semantics_evidence的实际页/块；没有依据时role=unspecified、meaning=unspecified或reported_error、level_kind=null。括号末位和拟合本身不等于stat或1sigma；数值和各个独立分量仍保留。', 'conditions': 'Only keys declared in the selected definition measurement_conditions_schema; otherwise []. Reference codes are not measurement conditions.', 'source_references': 'Preserve source reference codes separately as [{raw_code:original string,location:actual column/page}]; no guessed author/year/DOI and no new retrieval.', 'errors': 'If interpretation_state=parsed, values MUST be an object: symmetric_delta/variance/inverse_variance -> {delta:decimal string}; asymmetric_delta -> {minus:decimal string or null,plus:decimal string or null}; interval_endpoints -> {kind:interval,lower:decimal string or null,upper:decimal string or null,lower_closed:boolean,upper_closed:boolean}. Relative/percent need their stated basis and separate sides. If meaning or shape is not established, set unresolved with raw_text and reason; never mark parsed with values=null. Preserve all independent components; no average, zero-fill, 1sigma default or inferred stat/sys.'}
    rules['subject_link'] += (' 可用method=semantic_scope给出已取得局部和表头/章节的语义连接，特别是名字排版或省略重复主体时；'
                              '必须核对反证，不能靠全篇出现目标或模型记忆建立同一对象。程序核定位，不用逐字命中代替语义判断。')
    rules['scientific_review'] = ('不要把技术失败、缺少可选误差信息或可修引用格式交人工。原文足够明确自己核验；'
                                  '已证错误排除。仅有据可答且影响准入的科学歧义才填写local_admission.review_issue，'
                                  '星表用catalog_review_issue，给出具体待决事实、科学替代选项及影响、真实作用域/支持/反对证据；'
                                  '星表scope_kind默认matched_row，只有同一列定义对全部当前行产生同一歧义才用column_definition；scope_columns/support_columns/counter_columns只能填实际列名并有原始定义，不能自造引文。'
                                  '必须有unable；单位矛盾不提供confirm猜改单位。资料没有答案时保留未知而不是请人补事实。')
    rules['selected_subject_role']='subject_role is relative to the SELECTED property binding, not a label copied from subject_class_id. Use target when the source measures the explicitly selected subject/scale of this same identified target, including a named whole galaxy/host, its explicitly selected nucleus, a cluster aggregate or a selected whole system. host/component/member mean a different related subject outside that selected binding; never relabel another object or a member measurement as the selected aggregate. A profile word such as host does not by itself make the result off-target.'
    if catalog:
        for key in ('context_scope', 'subject_link', 'uncertainty_semantics', 'figure_boundary'):
            rules.pop(key)
    return rules
