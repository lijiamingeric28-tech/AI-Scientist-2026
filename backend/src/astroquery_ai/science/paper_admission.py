"""Independent, local evidence check before a paper proposal can be admitted.

This is a second interpretation, not a scientific truth oracle. Unsupported
anchors/ambiguous subjects go to the existing M07/M12 path, never to a guessed
target. It reads only pages already owned by the extraction batch.
"""

from __future__ import annotations
from astroquery_ai.science.measurements.admission_contracts import (
    AdmissionCheck,
    AdmissionChecks,
    AdmissionLocatorCheck,
    AdmissionLocatorChecks,
    Anchor,
    LocalContext,
    SubjectLink,
    matches_proposal_hash,
    normalized,
)
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from copy import deepcopy
from typing import Literal
from pydantic import Field, model_serializer
from astroquery_ai.runtime.codec import digest
from astroquery_ai.runtime.models import Contract
from astroquery_ai.science.catalogs import identifier_typography


from .papers.paper_evidence import (
    merge_locator_check,
    page_blocks,
    resolve_context_locator,
    context_fragments,
    document_frame,
    fit_native_blocks,
    target_quantity_pages,
    complete_native_evidence,
)
from .papers.native_values import (
    native_numeric_conflict,
    preserve_literal_native_coordinate,
    preserve_parenthetical_errors,
    positive_semantic_label,
    preserve_uncertainty_semantics,
)
from .papers.evidence_check import (
    check_local_evidence,
)

NATIVE_COLUMN_AUTHORITY_RULE = "提取器给出的column、unit、conditions、source_quality.note及源引文解释均是待核假说，不能当作原表头。逐项先在所给真实页块或页图中确定该数字所属的实际列名、该列原单位、表注及行标识，再与所选物理量比较；quantity_evidence须包含决定该物理量的实际列名/正文定义依据，不可只有对象名与数字。不能凭数字大小、常见星表列顺序或常识补出一个原文未印的列名或单位。如果实际表头或定义说明是另一物理量，应判different；只有真实依据不足才unresolved并保留未知。原单位未印且无明确适用的其他原文声明时留null，不推断为习惯单位。"


def independent_proposal_view(proposal):
    """Keep the full proposal saved, but do not feed its conclusions as facts."""
    raw = proposal.model_dump(mode="json")
    return {
        **{
            key: raw.get(key)
            for key in ("property_id", "raw_value", "value", "page", "row", "location_kind")
        },
        "claimed_coordinate_to_verify": {
            "unit": raw.get("unit"),
            "representation": raw.get("representation"),
        },
        "raw_error_mentions": [
            {key: e.get(key) for key in ("raw_text", "location")} for e in raw.get("errors", [])
        ],
    }


def admission_protocol_issues(proposal, check, target, pages, blocks):
    """Identify repairable locator failures, without deciding scientific truth.

    A genuinely unknown subject/role stays with source-level interpretation.
    A confident interpretation with unusable citations gets one local protocol
    repair instead of asking the user to select JSON/page-block identifiers.
    """
    if check is None:
        return ["missing_candidate_check"]
    if check.subject == "unresolved" or check.result_role == "unresolved":
        return []
    verified = check_local_evidence(
        proposal,
        check,
        target,
        pages,
        {},
        visible_blocks=blocks,
        image_pages=set(),
        require_quantity=True,
    )
    if verified["state"] != "unresolved":
        return []
    by_id = {b["block_id"]: b for b in blocks}
    anchors = [*check.subject_evidence, *check.role_evidence, *check.quantity_evidence]
    if check.subject_link:
        anchors += [
            *check.subject_link.local_evidence,
            *check.subject_link.scope_evidence,
            *check.subject_link.counter_evidence,
        ]
    if any(
        (
            a.page not in pages
            or any((k not in by_id or by_id[k]["page"] != a.page for k in a.block_ids))
            for a in anchors
        )
    ):
        return ["anchor_page_or_block_not_in_supplied_source"]
    if verified["reason"] == "local_subject_or_result_evidence_unresolved":
        return ["subject_locator_does_not_establish_local_to_named_scope_link"]
    return []


def protocol_repair_instruction(spec, proposals, checks, issues, pages, blocks):
    names = [
        spec["target"]["main_id"],
        *spec["target"].get("aliases", []),
        *(c.printed_subject for c in checks if c and c.printed_subject),
    ]
    names = list(dict.fromkeys([*names, *(n[4:] for n in names if n.startswith("PSR "))]))
    inventory = [
        {
            "printed_text": name,
            "actual_blocks": [
                {"block_id": b["block_id"], "page": b["page"]}
                for b in blocks
                if normalized(identifier_typography(name))
                in normalized(identifier_typography(b["text"]))
            ],
        }
        for name in names
    ]
    return {
        "schema": AdmissionLocatorChecks.model_json_schema(),
        "target": {key: spec["target"][key] for key in ("main_id", "aliases")},
        "candidates": [
            {
                "index": n,
                "property_id": p.property_id,
                "raw_value": p.raw_value,
                "page": p.page,
                "location_kind": p.location_kind,
                "role_evidence": [a.model_dump(mode="json") for a in c.role_evidence] if c else [],
            }
            for n, (p, c) in enumerate(zip(proposals, checks))
        ],
        "saved_pages": blocks,
        "instruction": "上次解释存在所列引用协议问题。只在同一批原件中修复，不能创造块、名字、别名或科学结论。本次只核对主体归属和连接，按小schema返回JSON，不重写主值、具体量或结果角色。subject=target只指请求target，不是文章主要对象。实际关系不足仍unresolved。printed_subject出现在哪个真实块，就引用那个块；局部数值与该块之间的语义连接仍需据原文说明。表格本身没有名字时，应把说明该表数据属于谁的前文块与表格块一起放入scope_evidence；不能声称无名的表标题直接写了目标名。scope_evidence允许跨页及多个实际块。不得只换标志为passed。",
        "previous_locator_fields": [
            {
                "printed_subject": c.printed_subject,
                "invalid_subject_blocks": [key for a in c.subject_evidence for key in a.block_ids],
            }
            if c
            else None
            for c in checks
        ],
        "locator_issues": issues,
        "literal_name_navigation": inventory,
        "navigation_boundary": "此索引仅表示名字实际出现的块，绝不证明数值归属。先检查原文连接，再在subject_evidence及scope_evidence中选择真实含名并实际支配该数值的块。上一答的块若没有printed_subject，不能声称它直接提及了该名字；使用实际前文表头/章节的块建立连接，反证应保留，关系不足仍未知。",
    }


def needs_independent_verification(proposal, check, core_pages, *, independent_primary=False):
    """Do not pay to recheck proposals already excluded by source admission."""
    return (
        (check["state"] == "unresolved" or (independent_primary and check["state"] == "passed"))
        and proposal.subject_role in {"target", "unresolved"}
        and (proposal.result_role in {"reported_result", "adopted_measurement", "unresolved"})
        and (proposal.location_kind in {"body", "table", "caption"})
        and (proposal.page in core_pages)
        and (not (proposal.source_quality and proposal.source_quality.state == "invalid"))
    )


def requires_visual_admission(proposal):
    """Figure/caption boundaries need page layout even with native PDF text."""
    return proposal.location_kind == "caption" or any(
        (
            re.search("\\b(?:fig(?:ure)?\\.?\\s*\\d+|plot)\\b", value or "", re.I)
            for value in (proposal.column, proposal.location_label)
        )
    )


def verification_instruction(spec, proposals, pages, *, visible_blocks=None, compact=False):
    instruction = {
        "instruction": "独立核对实际主体、具体量及结果角色，不信任候选标签。只用所给原件，逐index返回结论和真实Anchor；有块ID时quote填null由程序复制原文。名字未逐字命中、同一对象未在每行重印时，依据表头/章节/跨页原文给subject_link；不能凭全篇出现目标就绑定本段。首页主体和局部其他对象是必须核对的反证，局部范围优先于文章泛述。printed_subject只用实际印出的标识，不补全或发明别名。角色依据须包含数值和其报告含义：作者测量及明确合法采用可保留，处理设定、假设、试验常数不冒充测量。组件、波段、历元、方法、作者限制和结果身份按实际作用域分别带入context；不推导新量、选最佳值或补误差。关系确实不足才unresolved，格式和引用错误不让用户作科学判断。只返回schema规定的JSON。",
        "subject_rule": "先核对局部实际主体、表头及章节范围，再核目标关系。目标只在远处比较讨论中出现，不能把本段另一主体的数值归给目标。名称不逐字一致可用有出处的别名/命名空间解释，不能靠记忆发明关联或忽略真实分量。",
        "native_admission_boundary": "核对源报告的量；不要把缺失的可选方法、时标、历元、参考系或误差置信度当成另一物理量。遵守冻结条件中允许retain_unknown的范围。报告的轴向自转周期不自动建立质心计时身份；可保留明确周期和原单位，把未给出的计时身份单独留未知，不因此把period列改判成quantity_match=unresolved。仍禁止用轨道周期或频率反算替代。",
        "native_column_authority_rule": NATIVE_COLUMN_AUTHORITY_RULE,
        "missing_number_rule": "核对原页未给候选数值、引文是拼接或凭常识补数时，result_role=not_reported，并引用被核对位置的实际块。不要用unresolved让用户核验模型补出的数字。真正关系不明才unresolved。",
        "prompt_version": "local-source-admission/7-evidence-bound-review",
        "quantity_instruction": "必须填写quantity_match和quantity_evidence；exact或different都必须给非空的实际Anchor，可与role_evidence重复。核对是否已选同一物理量：总量与变化量/导数、模拟参数或处理设定不互认，不因单位相同互认。",
        "quantity_origin_rule": "独立检查拟合坐标的零点及定义：相对参考值的偏移、残差、扣趋势后的基线、事件幅度，即使表头称base或与总量同单位，也不是总量。固定参考常数本身不是新测量；不可加回参考值计算新测量。已有证据证明不同时quantity_match=different；远端定义未给出且无法确认时标unresolved。",
        "precision_rule": "必须读完整语法范围；uncertainty/error/precision/resolution of a measurement给出的数值是误差或精度，不是该量主值，quantity_match应为different。不能只摘出measurement of number短语忽略前面的uncertainty。独立误差不合并、不反推缺少的主值。",
        "subject_and_role_cautions": "同页出现目标不证明最大试验参数、搜索范围、仪器设定或校准量属于目标测量。printed_subject填写天体标识本身，明确的排版脚注符号及其说明另放context，不删真正的A/B等分量后缀；不能区分时标unresolved。",
        "independent_decisions": "subject、quantity_match、result_role是三项独立判断。quantity_match只判断所报告的物理量是否为所选量；一个确属目标的实测绝对主值，即使是拟合常数或只在一种方法下获得，仍可exact。另一对象的同种物理量通过subject=other排除；不把主体错误混作量的区别。设定值与实测值的区别主要由result_role表达，不因它出现于结果表就升级为测量。",
        "adoption_evidence_rule": "adopted_measurement专指有依据地转引、采用已有测量结果；须在role_evidence中指明原文如何把它作为已有测量报告（例如明确引用的测量表列）。仅说used/adopted/fixed/retained作为算法输入、在线处理参数、基准或试验设置，不证明采用了测量：按原文选assumption或calibration_constant。作者从本数据拟合得到的恒定物理主值是reported_result；constant不等于assumption。不能猜设定值来自哪次测量，也不能加回偏移构造未报告结果。",
        "figure_boundary": "单独填写value_location_kind=body/table/caption/plot/unresolved，判断数值实际所在位置，而非论文是否报告了测量。图内标题、面板标签、拟合摘要和坐标标注都是plot，即使有原生PDF文字层、无需估读。图内主值可以确实是reported_result，但位置仍禁止采集，不能改叫caption；不能要求它谎称为另一种物理量。只有正文、表格或图注自身报告的数值可采集。看版面，给出role_evidence位置依据。",
        "schema": AdmissionChecks.model_json_schema(),
        "target": {key: spec["target"][key] for key in ("main_id", "aliases")},
        "candidates": [
            dict(index=i, **independent_proposal_view(p)) for i, p in enumerate(proposals)
        ],
        "saved_pages": visible_blocks if visible_blocks is not None else page_blocks(pages),
    }
    from astroquery_ai.science.prompt_contracts import proposal_rules, property_view

    instruction["subject_link_rule"] = proposal_rules()["subject_link"]
    instruction['scientific_review_rule'] = (
        '面向人的问句、替代判断及选项影响使用简明中立的中文，不暗示默认答案。'
        '原文足够明确时系统自己解释和核验，不因名字排版、漏写重复主体、可选误差置信度/方法/历元缺失出题。'
        '可用semantic_scope连接已取得的局部和章节/表头证据，程序核定位，不以逐字别名匹配替代你的语义判断。'
        '只有实际影响准入的科学矛盾、必要主体关系或定义边界仍有争议，且现成原件支持可作答的替代判断时，'
        '填写review_issue：具体待决事实、问句、同一局部scope_evidence、支持/反对原文和每个选项的影响。'
        'issue_key按同一原件同一作用域同一歧义稳定命名，勿按候选序号命名；不同来源不合并。'
        '必须有unable；unit_semantics不得提供confirm来猜改单位，只能not_supported/unable。'
        '技术缺口、缺材料不能让人补事实，review_issue=null；已证错误直接拒绝，不出题。'
    )
    instruction['identity_interpretation'] = (
        '标准天体命名中的缩写、希腊字母、星座名展开和排版是名称表示解释，不要求论文另列SIMBAD交叉ID；'
        '结合已核身份独立判断并给实际局部作用域依据，不扩展成另一分量或无依据别名。'
        '文章主研究对象可以不是请求目标；局部明确报告/转引请求目标的测量仍可采集。'
        'subject、subject_link.relation及reason必须一致；不要输出自相矛盾的中途推理。'
    )
    instruction['native_unit_check'] = (
        '逐项核对原文实际单位而不是信任claimed_coordinate_to_verify.unit：unit_match=exact/different/unresolved/not_applicable，'
        'native_unit只写原文明确单位，unit_evidence定位该量实际单位声明。days/day/d等合法写法可exact，不因缩写不同出题。'
        '数值量缺单位证据不能猜。原文单位与具体量矛盾，或同一记录原文相互矛盾而无法核实正确单位时，'
        '这是unit_semantics科学歧义，应给具体review_issue和原文依据，选not_supported/unable，不默认改成惯用单位。'
        '单位缺失本身不一定有可作答问题；可选条件/误差角色不明仍保留未知。文本/类别量用not_applicable。'
        '只有properties中intrinsic_count_coordinate=true的具体计数：原文有明确计数含义和量证据但未写单位时，unit_match=not_applicable、native_unit=null；不要补写原文不存在的1。计数率、比例、百分比或缺失物理单位不适用。'
        '对原生对数坐标，核对原文量的定义和基准：log age且原文明确age in years时，原坐标的参考单位是yr，不是再取一次log的dex。'
        '无量纲的原生对数比值，原表头/定义明确了该坐标时，可native_unit=1并以该定义作unit_evidence；'
        '这仅解释无量纲坐标，不能给缺单位的物理量猜单位、填太阳基准或推导新值。'
    )
    from .unit_declarations import intrinsic_count_binding
    instruction["properties"] = []
    for binding in spec["properties"]:
        complete = property_view(binding)
        definition = complete["definition"]
        physical = {
            key: definition[key]
            for key in (
                "name_cn",
                "name_en",
                "quantity_key",
                "quantity_kind",
                "scope",
                "description",
                "aliases",
                "subject_class_id",
                "object_scale_id",
                "value_schema",
                "definition_qualifiers",
                "measurement_conditions_schema",
            )
            if key in definition
        }
        if definition.get("explanation"):
            physical["explanation"] = {
                key: definition["explanation"][key]
                for key in ("quantity", "subject", "boundary", "representation", "distinctions")
                if key in definition["explanation"]
            }
        instruction["properties"].append(
            {
                "property_id": binding["property_id"],
                "intrinsic_count_coordinate": intrinsic_count_binding(binding),
                'coordinate_interpretation_note': (
                    {'kind':binding['output_profile']['representation']['kind'],
                     'native_only':binding['output_profile']['representation'].get('native_coordinate_only',False),
                     'meaning':'An output logarithm is not proof that a source value is logarithmic. Verify the actual definition/header. For a source explicitly in dex or an established logarithmic coordinate, classify the coefficient as log10 (ln only for natural logarithms). Linear denotes the underlying physical ratio/age, not an already logarithmic coefficient. Never take a second logarithm of a printed log value or calculate a missing native log value.'}
                    if binding.get('output_profile',{}).get('representation',{}).get('kind') in {'log10','ln'} else None),
                "definition": physical,
                "quantity_focus": complete.get('quantity_focus',{}),
                "declared_measurand_dimension": binding.get('output_profile',{}).get('unit',{}).get('dimension') or definition.get('quantity_kind'),
                "measurand_unit_witness": {k:v for k,v in binding.get('output_profile',{}).get('unit',{}).items()
                    if k in {'canonical_symbol','dimension','kind','semantic_kind'}},
                "unit_witness_rule": "This approved unit declaration identifies the selected measurand's coordinate family, NOT an instruction to convert numbers. A source may use any equivalent unit of the same measurand. A related coordinate requiring a scientific formula is not that reported measurand. Preserve original coefficients/units; derive nothing here.",
                "stage_contract": "Native source admission; retain physical qualifiers, scoped identity contexts and their missing policies. Later output/operation permissions are checked separately.",
            }
        )
    instruction["decision_order"] = (
        "逐候选独立回答：①局部数值实际属于谁，与target.main_id是否为同一对象；subject=target仅指请求中的target，绝非本文主要对象。②它是哪一种物理量，不能用角色代替quantity_match。③原文把该数值报告为测量/明确转引测量，还是作为处理输入；同表各列逐列核对caption，不能沿用邻列的拟合身份。④用实际块建立该局部的连接；同一块可用于多个依据。真实拟合的常数主值保留；固定输入本身不给测量资格。各context均填主体及性质作用范围。"
    )
    schema = instruction["schema"]
    schema["$defs"]["AdmissionCheck"]["properties"]["subject_link"] = {
        "$ref": "#/$defs/SubjectLink"
    }
    schema["$defs"]["AdmissionCheck"]["required"] += ["subject_link"]
    schema['$defs']['AdmissionCheck']['required'] += ['unit_match', 'native_unit', 'unit_evidence']
    instruction["link_protocol"] = (
        "每项subject_link必须给对象和数值的连接依据，不填null。subject_evidence应引用实际出现printed_subject的块，不能给只有数值而没有该名字的块。名字在前面的表头、章节或首页时，用scope_evidence引用那个实际块，local_evidence指向数值所在块。直接具名的单句可将同一块用于local_evidence和scope_evidence。"
    )
    if compact:
        instruction["prompt_version"] = "local-source-admission/7-evidence-bound-review-compact"
        schema = instruction["schema"]
        schema["$defs"]["AdmissionCheck"]["properties"]["reason"]["maxLength"] = 180
        schema["$defs"]["AdmissionCheck"]["required"] += ["quantity_match", "quantity_evidence"]
        schema["$defs"]["LocalContext"]["properties"]["text"]["maxLength"] = 300
        schema["$defs"]["LocalContext"]["required"] += ["subject_scope", "property_scope"]
        blocks = instruction["saved_pages"]
        complete = all(
            (
                p.page in pages
                and pages[p.page].strip()
                and (
                    normalized("".join((b["text"] for b in blocks if b["page"] == p.page)))
                    == normalized(pages[p.page])
                )
                for p in proposals
            )
        )
        if complete:
            schema["$defs"]["Anchor"]["properties"]["quote"] = {"type": "null", "default": None}
        instruction["anchor_protocol"] = (
            "已有原文块时只返回实际block_ids，quote填null；服务端复制完整原文，不回抄或拼接引文。每个index都给结论，reason只写一句不超过180字的判断依据；context用短说明，完整出处仍由Anchor保留。候选没有提供第一模型的主体/角色结论，须独立依据saved_pages判定，不能把候选数值当成已经成立的事实。"
        )
    return instruction
