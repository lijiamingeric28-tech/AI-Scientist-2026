"""Compose ordinary services for the single main dispatcher."""

from .workflow.context import ScienceContext
from .workflow.catalog_service import CatalogService
from .workflow.literature_service import LiteratureService
from .workflow.paper_service import PaperService
from .workflow.attachment_service import AttachmentService
from .workflow.quality_service import QualityService
from .workflow.insight_service import InsightService
from .workflow.orchestration_service import OrchestrationService


class SciencePipeline:
    def __init__(self, application):
        context = ScienceContext(application)
        self.services = [
            CatalogService(context),
            LiteratureService(context),
            PaperService(context),
            AttachmentService(context),
            QualityService(context),
            InsightService(context),
            OrchestrationService(context),
        ]
        self.handlers = {}
        for service in self.services:
            for kind, method in service.handlers.items():
                if kind in self.handlers:
                    raise ValueError("duplicate scientific job handler")
                self.handlers[kind] = getattr(service, method)
        self.advance = next(s.advance for s in self.services if isinstance(s, OrchestrationService))
