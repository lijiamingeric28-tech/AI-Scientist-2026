'Whole-source interpretation of already collected results and repeated mentions.'

from decimal import Decimal, InvalidOperation

from typing import Literal

import re

from pydantic import Field, ValidationError, model_validator
from astroquery_ai.registry.models import Representation

from astroquery_ai.runtime.models import Contract

from astroquery_ai.science.measurements.admission_contracts import AdmissionCheck, Anchor, normalized

from astroquery_ai.science.paper_admission import page_blocks

from astroquery_ai.science.measurements.contracts import SourceQualityProposal, ErrorProposal

from .catalogs import identifier_typography

def source_review_blocks(pages, proposals, verifications, target, *, byte_limit=32000, context_pages=(), context_blocks=(), context_neighbors=False):
    """Carry saved anchors before surrounding pages, without numeric grep.

    A parsed decimal often differs from native Unicode/scientific notation.
    Original headers, role/quantity anchors and prior context remain necessary
    when reviewing that number. Selection is navigation, never permission.
    """
    blocks = page_blocks(pages)
    by_id = {b['block_id']: b for b in blocks}
    positions = {b['block_id']: i for i,b in enumerate(blocks)}
    ordered = []
    for verification in verifications:
        check = (verification or {}).get('check') or {}
        anchors = [a for key in ('quantity_evidence', 'role_evidence', 'subject_evidence', 'unit_evidence') for a in check.get(key, [])]
        anchors += [c['anchor'] for c in check.get('context', [])]
        anchors += [a for key in ('local_evidence', 'scope_evidence', 'counter_evidence') for a in (check.get('subject_link') or {}).get(key, [])]
        for anchor in anchors:
            if anchor.get('block_ids'):
                ordered.extend((by_id[key] for key in anchor['block_ids'] if key in by_id and by_id[key]['page'] == anchor['page']))
            elif anchor.get('quote'):
                ordered.extend((b for b in blocks if b['page'] == anchor['page'] and normalized(anchor['quote']) in normalized(b['text'])))
    ordered.extend([b for b in blocks if b['page'] == 1][:4])
    names = [target['main_id'], *target.get('aliases', [])]
    names.extend((name[4:] for name in list(names) if name.startswith('PSR ')))
    identity = next((b for b in blocks if any((normalized(identifier_typography(name)) in normalized(identifier_typography(b['text'])) for name in names))), None)
    if identity:
        ordered.append(identity)
    wanted_pages = {p.page for p in proposals if p.page is not None}
    wanted_pages.update(context_pages)
    ordered.extend((b for b in blocks if b['page'] in wanted_pages))
    for block in context_blocks:
        if block.get('block_id') in by_id:
            ordered.append(by_id[block['block_id']])
            if context_neighbors:
                # Reader notes can start halfway through a method or table
                # explanation. Carry bounded, physically adjacent original
                # blocks rather than treating a continuation as complete.
                # No keyword search or interpretation is performed here.
                pos=positions[block['block_id']]
                start=pos-2
                if pos and blocks[pos-1]['page']!=blocks[pos]['page']:
                    start=pos-3
                ordered.extend(blocks[max(0,start):pos+2])
        elif block.get('text') and block['text'] in pages.get(block.get('page'),''):
            ordered.append(block)
    # Carry the reader's actual scoped notes, including distant footnotes.
    # Whole-paper keyword matches are not evidence that a warning concerns
    # this quantity/object and previously pulled unrelated sections in here.
    for proposal in proposals:
        quality=getattr(proposal,'source_quality',None)
        for quote in [*(quality.raw_info if quality else []),*(quality.caution_quotes if quality else [])]:
            if quote in by_id:
                ordered.append(by_id[quote])
            elif quote:
                ordered.extend(b for b in blocks if quote in b['text'])
    selected, omitted, used = ([], [], 0)
    for block in {b['block_id']: b for b in ordered}.values():
        size = len(block['text'].encode())
        if used + size > byte_limit:
            omitted.append(block['block_id'])
        else:
            selected.append(block)
            used += size
    return (selected, omitted)


def review_image_pages(proposals,pages,*,table_layout=False):
    return sorted({p.page for p in proposals if p.page and
        (len(pages.get(p.page,'').strip())<80 or table_layout and p.location_kind=='table')})


def focused_review_blocks(pages, proposals, target, notes=()):
    """Singleton overflow: original anchors and adjacent layout, never numeric grep.

    Explicit quantity/unit/error/subject anchors and cited caution blocks remain
    mandatory, including distant notes. Unselected material is reported, not
    declared examined. A caller must not dispatch if a mandatory anchor is lost.
    """
    blocks=page_blocks(pages);by_id={b['block_id']:b for b in blocks}
    wanted=set();mandatory=set();unresolved=[]
    def anchors(value):
        if isinstance(value,dict):
            ids=value.get('block_ids') or []
            for key in ids:
                if key in by_id and by_id[key]['page']==value.get('page'):
                    mandatory.add(key)
                else:unresolved.append(key)
            if value.get('quote') and value.get('page'):
                quote=normalized(value['quote'])
                mandatory.update(b['block_id'] for b in blocks if b['page']==value['page'] and
                    (quote in normalized(b['text']) or normalized(b['text']) in quote))
            for v in value.values():anchors(v)
        elif isinstance(value,list):
            for v in value:anchors(v)
    for proposal in proposals:
        raw=proposal.model_dump(mode='json');anchors(raw.get('local_admission'))
        for error in raw['errors']:anchors(error.get('semantics_evidence',[]))
        quote=normalized(proposal.source_quote)
        local=[b for b in blocks if b['page']==proposal.page]
        mandatory.update(b['block_id'] for b in local if quote and
            (quote in normalized(b['text']) or normalized(b['text']) in quote))
        # Keep original header/footer layout alongside the actual row. These
        # are navigation regions, not a guessed column/quantity interpretation.
        if proposal.location_kind=='table':wanted.update(b['block_id'] for b in [*local[:2],*local[-2:]])
        quality=raw.get('source_quality') or {}
        for key in [*quality.get('raw_info',[]),*quality.get('caution_quotes',[])]:
            if key in by_id:mandatory.add(key)
            else:mandatory.update(b['block_id'] for b in blocks if key and normalized(key) in normalized(b['text']))
    wanted.update(mandatory)
    pages_in_scope={by_id[k]['page'] for k in wanted}
    wanted.update(b['block_id'] for b in notes if b.get('block_id') in by_id and b.get('page') in pages_in_scope)
    original_wanted=set(wanted)
    for i,block in enumerate(blocks):
        if block['block_id'] in original_wanted:
            wanted.update(b['block_id'] for b in blocks[max(0,i-1):i+2] if b['page']==block['page'])
    # Identity/title is context only; it never replaces the value's local subject.
    wanted.update(b['block_id'] for b in blocks if b['page']==1 and b in blocks[:2])
    selected=[b for b in blocks if b['block_id'] in wanted]
    return selected,[b['block_id'] for b in blocks if b['block_id'] not in wanted],unresolved


def initial_review_groups(items, candidates, pages, *, target=None, property_bytes=0, context_pages=(),context_blocks=(),context_neighbors=False,table_layout=False):
    """Capacity planning before review, never failure-triggered subdivision."""
    group, native_pages, scan_pages = [], set(), set()
    for item in items:
        page = candidates[item['id']]['proposal'].get('page')
        proposal=candidates[item['id']]['proposal']
        visual = {page} if page and (len(pages.get(page,'').strip()) < 80 or table_layout and proposal.get('location_kind')=='table') else set()
        proposed = native_pages | ({page} if page else set())
        size = sum(len(pages.get(p,'').encode()) for p in proposed)
        if target is not None:
            from .measurements.contracts import MeasurementProposal
            from .paper_admission import independent_proposal_view
            from astroquery_ai.runtime.codec import canonical
            trial=[MeasurementProposal.model_validate(candidates[v['id']]['proposal']) for v in [*group,item]]
            prior=[{'check':p.local_admission.model_dump(mode='json') if p.local_admission else {}} for p in trial]
            selected,_=source_review_blocks(pages,trial,prior,target,byte_limit=180000,context_pages=context_pages,context_blocks=context_blocks,context_neighbors=context_neighbors)
            # Account for the actual quoted blocks and candidate/error payload,
            # plus schema, definitions and fixed review instructions. Initial
            # grouping precedes dispatch; it is never a failed-call split.
            size=len(canonical({'source_blocks':selected,'items':[{**independent_proposal_view(p),
                'claimed_errors_to_verify':[e.model_dump(mode='json') for e in p.errors]} for p in trial]}))
            size+=len(canonical(SourceReview.model_json_schema()))+property_bytes+18000
        if group and (len(group) >= 24 or len(scan_pages | visual) > 4 or size > (92000 if target is not None else 100000)):
            yield group
            group, native_pages, scan_pages = [], set(), set()
        group.append(item)
        native_pages.update({page} if page else set())
        scan_pages.update(visual)
    if group:
        yield group

class SourceItemCheck(Contract):
    item_id: str
    assessment: AdmissionCheck
    source_quality: SourceQualityProposal | None = None
    native_representation: Literal['linear','log10','ln','magnitude','category','boolean','text','relation'] | None = None
    coordinate_reference_unit: str | None = None
    representation_parameters: Representation | None = None
    correct_native_unit: bool = False
    value_match: Literal['exact','different','unresolved'] = 'unresolved'
    native_numeric_literal: str | None = None
    errors_match: Literal['exact','different','unresolved','not_reported'] | None = None
    corrected_errors: list[ErrorProposal] | None = Field(default=None,max_length=24)

    @model_validator(mode='after')
    def consistent_native_coordinate(self):
        identity = self.assessment.quantity_identity
        if (identity and identity.native_coordinate_kind is not None
                and self.native_representation != identity.native_coordinate_kind):
            raise ValueError('native_representation contradicts quantity_identity.native_coordinate_kind; '
                             'report the same evidenced SOURCE coordinate in both, preserving the original coefficient')
        return self

class SameResultGroup(Contract):
    canonical_id: str
    member_ids: list[str] = Field(min_length=2, max_length=24)
    discriminator: str = Field(min_length=3)
    evidence: list[Anchor] = Field(min_length=1, max_length=6)
    reason: str = Field(min_length=1)

class SourceReview(Contract):
    items: list[SourceItemCheck] = Field(max_length=24)
    same_results: list[SameResultGroup] = Field(default_factory=list, max_length=12)
    limitations: list[str] = Field(default_factory=list)


def source_review_outcome(response):
    """A malformed assessment cannot erase valid assessments of this source."""
    items, errors, seen = {}, [], set()
    rows = response.get('items') if isinstance(response, dict) else None
    if not isinstance(rows, list) or len(rows) > 24:
        return SourceReview(items=[]), [{'reason': 'source_review_batch_schema'}]
    for ordinal, raw in enumerate(rows):
        try:
            if isinstance(raw,dict):
                raw=dict(raw)
                assessment=raw.get('assessment') or {}
                if (raw.get('native_representation') in {'log10','ln'}
                        and isinstance(raw.get('coordinate_reference_unit'),str)
                        and assessment.get('native_unit') in {None,'1','dex'}
                        and (assessment.get('unit_match')=='exact' or
                             assessment.get('unit_match') in {'not_applicable','unresolved'} and raw.get('value_match')=='exact')
                        and assessment.get('quantity_match')=='exact' and assessment.get('unit_evidence')):
                    # The printed logarithmic coefficient has no ordinary
                    # physical unit. The independent reader separately states
                    # its explicit reference basis, with original unit anchors.
                    # Consume that structured basis claim, not reason prose or
                    # a target-unit guess. A different/conflicting declaration
                    # is never repaired this way. Raw model verdict is retained
                    # in the immutable paid response/checkpoint.
                    raw['assessment']={**assessment,'native_unit':raw['coordinate_reference_unit'],
                                       'unit_match':'exact'}
                # Optional arithmetic parameters are not the original value,
                # subject or unit verdict. A malformed speculative zero point
                # must not erase an otherwise valid independent assessment.
                if raw.get('representation_parameters') is not None:
                    parameters=raw['representation_parameters']
                    assessment=raw.get('assessment') or {}
                    if (isinstance(parameters,dict) and parameters.get('kind') in {'log10','ln'}
                            and isinstance(parameters.get('reference_unit'),str)
                            and assessment.get('native_unit') is None and assessment.get('unit_match')=='exact'
                            and assessment.get('unit_evidence')):
                        # The independent reader supplied the physical reference
                        # unit in its coordinate field; route that exact claim.
                        # Do not supply a zero point or missing numeric parameter.
                        raw['assessment']={**assessment,'native_unit':parameters['reference_unit']}
                    try:
                        Representation.model_validate(raw['representation_parameters'])
                    except ValidationError:
                        errors.append({'item_id':raw.get('item_id'),'reason':'unverified_representation_parameters',
                                       'raw_parameters':raw['representation_parameters']})
                        raw['representation_parameters']=None
            item = SourceItemCheck.model_validate(raw)
            if item.item_id in seen:
                items.pop(item.item_id, None)
                errors.append({'item_id': item.item_id, 'reason': 'duplicate_item'})
                continue
            seen.add(item.item_id)
            items[item.item_id] = item
        except ValidationError as exc:
            errors.append({'ordinal': ordinal, 'reason': 'source_review_item_schema',
                           'fields': [{'loc': list(e['loc']), 'type': e['type']} for e in exc.errors()]})
    groups = []
    raw_groups = response.get('same_results', [])
    if not isinstance(raw_groups, list) or len(raw_groups) > 12:
        raw_groups = []
        errors.append({'reason': 'same_result_groups_schema'})
    for raw in raw_groups:
        try:
            if isinstance(raw,dict) and isinstance(raw.get('member_ids'),list):
                # The canonical location is explicitly declared as belonging
                # to this result. Some responses list only its other mentions;
                # normalize that representation, never infer extra membership.
                if raw.get('canonical_id') not in raw['member_ids']:
                    raw={**raw,'member_ids':[raw.get('canonical_id'),*raw['member_ids']]}
            groups.append(SameResultGroup.model_validate(raw))
        except ValidationError:
            errors.append({'reason': 'same_result_group_schema'})
    limitations = response.get('limitations', [])
    return SourceReview(items=list(items.values()), same_results=groups,
                        limitations=limitations if isinstance(limitations, list) and all(isinstance(t,str) for t in limitations) else []), errors

class SourceInformationItem(Contract):
    item_id: str
    source_quality: SourceQualityProposal

class SourceInformationReview(Contract):
    items: list[SourceInformationItem] = Field(max_length=24)

class SourceInformationSelection(Contract):
    item_id: str
    state: Literal['checked', 'unresolved', 'invalid']
    checked_ids: list[str]
    caution_ids: list[str]
    note: str

class SourceInformationSelections(Contract):
    items: list[SourceInformationSelection] = Field(max_length=24)

def equal_reported_value(left, right):
    if left['property_id'] != right['property_id'] or left['representation'] != right['representation']:
        return False
    if left['value']['kind'] != right['value']['kind'] or left['limit'] != right['limit']:
        return False
    if left['value']['kind'] in {'real', 'integer'}:
        if Decimal(left['value']['value']) != Decimal(right['value']['value']):
            return False
    elif left['value'] != right['value']:
        return False
    try:
        from .units import parse_unit
        a = parse_unit(left['unit'])
        b = parse_unit(right['unit'])
        if a != b:
            return False
    except (ValueError, TypeError):
        if left['unit'] != right['unit']:
            return False

    def known(doc):
        return {c['key']: c['value'] for c in doc['conditions'] if c['state'] == 'known'}
    a, b = (known(left), known(right))
    if any((a[key] != b[key] for key in a.keys() & b.keys())):
        return False
    for error in left['errors']:
        for other in right['errors']:
            if error['interpretation_state'] == other['interpretation_state'] == 'parsed' and error['kind'] == other['kind'] and (error['role'] == other['role']):
                av, bv = (error['values'], other['values'])
                if isinstance(av, dict) and isinstance(bv, dict) and (av.keys() == bv.keys()):
                    try:
                        if any((Decimal(str(av[k])) != Decimal(str(bv[k])) for k in av)):
                            return False
                    except (InvalidOperation, TypeError):
                        if av != bv:
                            return False
    return True

def validated_group(group, proposals, eligible_ids, blocks):
    ids = group.member_ids
    if len(set(ids)) != len(ids) or group.canonical_id not in ids or set(ids) - eligible_ids:
        return None
    canonical = proposals[group.canonical_id]
    if any((not equal_reported_value(canonical, proposals[mid]) for mid in ids)):
        return None
    if any((proposals[mid]['location_kind'] == 'table' for mid in ids)) and canonical['location_kind'] != 'table':
        return None
    canonical_conditions = {c['key']: c['value'] for c in canonical['conditions'] if c['state'] == 'known'}
    for mid in ids:
        member = proposals[mid]
        if any((c['state'] == 'known' and canonical_conditions.get(c['key']) != c['value'] for c in member['conditions'])):
            return None
        for error in member['errors']:
            keys = ('kind', 'role', 'meaning', 'interpretation_state', 'values', 'level_kind', 'level_values')
            if not any((all((error.get(key) == other.get(key) for key in keys)) and (error['interpretation_state'] == 'parsed' or error['raw_text'] == other['raw_text']) for other in canonical['errors'])):
                return None
    try:
        Decimal(group.discriminator)
        return None
    except InvalidOperation:
        pass
    quotes = []
    for anchor in group.evidence:
        if anchor.block_ids:
            pieces = [blocks.get(key) for key in anchor.block_ids]
            if any((piece is None or piece['page'] != anchor.page for piece in pieces)):
                return None
            quotes.extend((piece['text'] for piece in pieces))
        elif anchor.quote and any((piece['page'] == anchor.page and normalized(anchor.quote) in normalized(piece['text']) for piece in blocks.values())):
            quotes.append(anchor.quote)
        else:
            return None
    covered_pages = {anchor.page for anchor in group.evidence}
    if any((proposals[mid].get('page') is not None and proposals[mid]['page'] not in covered_pages for mid in ids)):
        return None
    return {**group.model_dump(mode='json'), 'source_quotes': quotes}
