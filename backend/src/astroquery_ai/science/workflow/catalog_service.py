'Compatibility service facade with one explicit handler table.'

from astroquery_ai.science.catalog.rows import extract_verified_rows

from .context import ModuleService

import astroquery_ai.science.catalog.discovery as _operations_0

import astroquery_ai.science.catalog.extraction as _operations_1

import astroquery_ai.science.catalog.identity as _operations_2

import astroquery_ai.science.catalog.planning as _operations_3

class CatalogService(ModuleService):
    handlers = {'catalog_discover': 'discover_catalogs', 'catalog_extract': 'extract_catalog', 'attachment_extract': 'extract_catalog'}
    discovered_schema = _operations_0.discovered_schema
    discover_catalogs = _operations_0.discover_catalogs
    extract_catalog = _operations_1.extract_catalog
    interpret_identity_rows = _operations_2.interpret_identity_rows
    execution_plans = staticmethod(_operations_3.execution_plans)
    catalog_document = _operations_3.catalog_document
    validate_column_plan = staticmethod(_operations_3.validate_column_plan)
    header_prompt = staticmethod(_operations_3.header_prompt)
    extract_verified_rows = extract_verified_rows
