"""Compatibility exports for source measurement contracts and assembly."""

from astroquery_ai.science.measurements.contracts import (
    CatalogFieldRole,
    CatalogSemanticAnchor,
    ConditionProposal,
    ContextRequest,
    ErrorProposal,
    ExtractionBatch,
    MeasurementProposal,
    ReportedReferenceProposal,
    SourceQualityProposal,
    evidence_ref,
    validated_batch,
)
from astroquery_ai.science.measurements.assembly import EvidenceExtractor
