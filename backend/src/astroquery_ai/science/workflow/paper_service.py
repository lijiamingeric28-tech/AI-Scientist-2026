"""Compatibility service facade with one explicit handler table."""
from .context import ModuleService
import astroquery_ai.science.papers.acquisition as _operations_0
import astroquery_ai.science.papers.reading as _operations_1
import astroquery_ai.science.papers.reconciliation as _operations_2
from astroquery_ai.science.papers import figures
from astroquery_ai.science.papers import references

class PaperService(ModuleService):
    handlers = {'acquire_window': 'acquire_window', 'acquire_work': 'acquire_work', 'paper_batch': 'extract_paper', 'source_reconcile': 'reconcile_source',
                'paper_figures': 'discover_figures', 'paper_figure_page': 'extract_figures'}
    handlers['citation_enrich'] = 'enrich_references'
    enrich_references = references.enrich_references
    discover_figures = figures.discover_figures
    extract_figures = figures.extract_figures
    acquire_window = _operations_0.acquire_window
    acquire_work = _operations_0.acquire_work
    acquisition_gap = _operations_0.acquisition_gap
    acquire_one = _operations_0.acquire_one
    verify_download_identity = _operations_0.verify_download_identity
    reader_settings = _operations_1.reader_settings
    extract_paper = _operations_1.extract_paper
    single_scope_protocol_fallback = _operations_1.single_scope_protocol_fallback
    close_reading_gap = _operations_1.close_reading_gap
    refine_batch = _operations_1.refine_batch
    extraction_instruction = staticmethod(_operations_1.extraction_instruction)
    reader_inputs = staticmethod(_operations_1.reader_inputs)
    extract_paper_once = _operations_1.extract_paper_once
    reconcile_source = _operations_2.reconcile_source
    reconcile_source_once = _operations_2.reconcile_source_once
