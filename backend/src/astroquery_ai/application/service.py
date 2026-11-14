"Single application composition root and stable service facade."

from __future__ import annotations

from pathlib import Path

from astroquery_ai.runtime.budget import Budget

from astroquery_ai.runtime.calls import ModelGateway

from astroquery_ai.runtime.codec import digest, loads

from astroquery_ai.runtime.configuration import Configuration

from astroquery_ai.runtime.delivery import DeliveryService

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.runtime.http import ScientificHTTP

from astroquery_ai.runtime.repository import Repository

from astroquery_ai.runtime.reviews import ReviewService

from astroquery_ai.runtime.storage import ArtifactStore

from astroquery_ai.registry.service import RegistryService

from astroquery_ai.science.identity import SimbadIdentity

from astroquery_ai.query import drafts as _drafts

from astroquery_ai.application import views as _views


class Application:
    def __init__(self, root: Path, *, allow_synthetic=False):
        from astroquery_ai.runtime.astronomy import configure_offline_tables

        configure_offline_tables()
        self.root = root.resolve()
        self.repository = Repository(self.root / "runtime.sqlite3")
        self.configuration = Configuration(self.root)
        self.budget = Budget(self.repository)
        self.artifacts = ArtifactStore(self.root / "artifacts", self.repository)
        self.registry = RegistryService(
            self.root / "registry", self.repository, allow_synthetic=allow_synthetic
        )
        from astroquery_ai.science.knowledge import KnowledgeService

        self.knowledge = KnowledgeService(
            self.root / "knowledge" / "insights", self.repository, self.registry
        )
        from astroquery_ai.registry.workbench import RegistryWorkbench
        self.registry_workbench = RegistryWorkbench(self.registry, self.repository, self.knowledge)
        from astroquery_ai.science.user_knowledge_store import UserKnowledgeStore

        self.user_knowledge = UserKnowledgeStore(data_dir=self.root)
        self.http = ScientificHTTP(self.repository)
        from astroquery_ai.runtime.profiles import ProfileAuthority

        self.profile_authority = ProfileAuthority(self)
        self.models = ModelGateway(
            self.configuration, self.budget, profile_authorizer=self.profile_authority.authorize
        )
        from astroquery_ai.runtime.science_capabilities import authorize_verification

        self.models.verification_authorizer = lambda *args: authorize_verification(self, *args)
        self.identity = SimbadIdentity(self.http, self.artifacts)
        self.reviews = ReviewService(self.repository)
        from astroquery_ai.runtime.parsing import Parsers

        self.parsers = Parsers()
        self.delivery = DeliveryService(self.repository, self.artifacts, knowledge_store=self.user_knowledge)
        from astroquery_ai.runtime.history import History
        from astroquery_ai.runtime.maintenance import Maintenance

        self.history, self.maintenance = (History(self), Maintenance(self))
        from astroquery_ai.application.material_analysis import MaterialAnalysisService
        self.material_analysis = MaterialAnalysisService(self)
        from astroquery_ai.runtime.legacy import LegacyHistory

        self.legacy = LegacyHistory(self)
        from astroquery_ai.application.job_failures import JobFailures

        self.failures = JobFailures(self)
        from astroquery_ai.runtime.product_qualifications import install_release
        from astroquery_ai.runtime.provider import provider_identity
        if (not allow_synthetic and self.configuration.runtime.get('dashscope_api_key')
                and provider_identity(self.configuration.runtime.get('dashscope_base_url',''))):
            from astroquery_ai.runtime.product_libraries import ensure_libraries
            ensure_libraries(self)
            install_release(self)

    async def parse_owned(self, task_id, artifact_id, operation, **options):
        import asyncio
        identity = digest({'artifact':artifact_id, 'operation':operation, 'options':options})
        download_verification = options.pop('download_verification', False)
        if download_verification:
            from astroquery_ai.science.feedback_retrieval import enabled as feedback_enabled
            with self.repository.read() as conn:
                task = self.repository.task(conn, task_id)
                ref = loads(task['query_ref']) if task['query_ref'] else None
                spec = self.repository.object(conn, task_id, 'confirmed_query', ref['id'], ref['version']) if ref else {}
                acquiring = conn.execute("select 1 from jobs where task_id=? and kind='acquire_work' and status='running'", (task_id,)).fetchone()
            if operation != 'inspect_pdf' or not feedback_enabled(spec) or not acquiring:
                raise DomainError('DOWNLOAD_INSPECTION_SCOPE', '超页技术完整性核验仅供本候选版的在途正文获取')
        locks = self.__dict__.setdefault('_parse_locks', {})
        cache = self.__dict__.setdefault('_parsed_artifacts', {})
        lease = self.artifacts.lease(task_id, artifact_id, seconds=options.get("timeout", 90) + 30)
        try:
            _, path = self.artifacts.read_owned(task_id, artifact_id)
            if operation in {'inspect_pdf', 'page_image', 'figure_candidates', 'figure_crop'}:
                from astroquery_ai.science.documents import maximum_pages
                with self.repository.read() as conn:
                    limit = maximum_pages(self.repository, conn, task_id)
                if limit is not None:
                    probes = self.__dict__.setdefault('_physical_pdf_probes', {})
                    if artifact_id not in probes:
                        probes[artifact_id] = await self.parsers.run('probe_pdf', path, timeout=30)
                    if probes[artifact_id]['page_count'] > limit and not download_verification:
                        raise DomainError('PDF_PHYSICAL_PAGE_LIMIT', 'PDF超过本次实际页数门槛，整份跳过模型阅读与图证')
            async with locks.setdefault(identity, asyncio.Lock()):
                if identity not in cache:
                    with self.repository.read() as conn:
                        saved = next((x for x in self.repository.objects(conn, task_id, 'parser_cache')
                                      if x['cache_key'] == identity), None)
                    if saved:
                        cache[identity] = {'image_artifact':saved['artifact']}
                    else:
                        parsed = await self.parsers.run(operation, path, **options)
                        if isinstance(parsed, bytes):
                            artifact = self.artifacts.write(parsed, 'image/png')
                            with self.repository.transaction() as conn:
                                self.artifacts.register(conn, task_id, 'parser-cache-' + identity, artifact)
                                self.repository.put_object(conn, task_id, 'parser_cache', identity, 1,
                                    {'cache_key':identity, 'source_artifact_id':artifact_id,
                                     'operation':operation, 'options':options, 'artifact':artifact})
                            cache[identity] = {'image_artifact':artifact}
                        else:
                            cache[identity] = parsed
                if isinstance(cache[identity], dict) and 'image_artifact' in cache[identity]:
                    artifact = cache[identity]['image_artifact']
                    with self.repository.transaction() as conn:
                        self.artifacts.register(conn, task_id, 'parser-cache-' + identity, artifact)
                    return self.artifacts.path(artifact['relative_path']).read_bytes()
                from copy import deepcopy
                return deepcopy(cache[identity])
        finally:
            self.artifacts.release(lease)

    def _profile_state(self, owner):
        with self.repository.read() as conn:
            row = conn.execute(
                "SELECT payload FROM settings WHERE key=?", ("profile:" + owner,)
            ).fetchone()
            if not row:
                return "trial"
            profile = loads(row[0])
            if profile.get("synthetic"):
                return profile.get("state", "trial") if self.registry.allow_synthetic else "trial"
            from astroquery_ai.runtime.provider import compatible
            if profile.get("state") != "validated" or not compatible(
                profile, self.configuration.runtime.get("dashscope_base_url", "")
            ):
                return "trial"
            try:
                self.profile_authority.load(conn, owner)
            except DomainError:
                return "trial"
            return "validated"

    create = _drafts.create
    _draft = _drafts._draft
    _question = _drafts._question
    _save_draft = _drafts._save_draft
    omission_hash = staticmethod(_drafts.omission_hash)
    draft_action = _drafts.draft_action
    _bind_target = _drafts._bind_target
    _queue_property_selection = _drafts._queue_property_selection
    _select_properties = _drafts._select_properties
    request_prompt = staticmethod(_drafts.request_prompt)
    prepare = _drafts.prepare
    view = _views.view
