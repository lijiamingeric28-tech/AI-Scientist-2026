"""Compatibility service facade with one explicit handler table."""
from .context import ModuleService
from .uncertainty_service import UncertaintyInterpretationMixin
from .scientific_conditions_service import ScientificConditionsMixin
import astroquery_ai.science.processing.assessment as _operations_0
import astroquery_ai.science.processing.normalization as _operations_1
import astroquery_ai.science.processing.review_application as _operations_2
import astroquery_ai.science.unified_quality as _unified
import astroquery_ai.science.archive_comparison as _comparison

class QualityService(ScientificConditionsMixin, UncertaintyInterpretationMixin, ModuleService):
    handlers = {'assess_batch': 'assess_batch', 'normalize': 'normalize', 'apply_review': 'apply_review', 'apply_source_recheck': 'apply_source_recheck', 'review_source_gap': 'review_source_gap', 'interpret_uncertainty': 'interpret_uncertainty'}
    handlers.update(quality_verify='quality_verify',quality_reextract='quality_reextract',quality_citation_enrich='quality_citation_enrich')
    quality_verify=_unified.verify
    quality_reextract=_unified.reextract
    quality_citation_enrich=_unified.enrich_citations
    handlers['compare_results']='compare_results'
    compare_results=_comparison.compare_results
    review_source_gap = _operations_0.review_source_gap
    apply_source_recheck = _operations_0.apply_source_recheck
    assess_batch = _operations_0.assess_batch
    normalize = _operations_1.normalize
    apply_review = _operations_2.apply_review
    reopen_invalid_answer = _operations_2.reopen_invalid_answer
    apply_review_once = _operations_2.apply_review_once
