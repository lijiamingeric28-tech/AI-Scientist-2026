"""M05 official attachment acquisition; M03 remains the sole table interpreter."""

from __future__ import annotations
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from astroquery_ai.runtime.codec import digest, loads
from astroquery_ai.runtime.errors import DomainError
from ..attachments import official_links, acquired_format
from .context import ModuleService


class AttachmentService(ModuleService):
    handlers = {"attachment_discover": "discover"}

    async def discover(self, job):
        tid, work_id = job["task_id"], job["payload"]["work_id"]
        with self.repo.read() as conn:
            spec = self.spec(conn, tid)
            ledger = self.repo.objects(conn, tid, "read_ledger")[0]
            if work_id not in ledger["selections"]:
                raise DomainError("ATTACHMENT_GRANT_MISSING", "未入选作品不得枚举附件")
            source = self.repo.object(conn, tid, 'source', work_id)
            if source.get('kind') != 'paper' or not source.get('qualification_ref') or not source.get('artifact'):
                raise DomainError('ATTACHMENT_PARENT_NOT_ACQUIRED', '只有已取得并通过资格检查的正文可发现附件')
            work = self.repo.object(conn, tid, "work", work_id)
            allowed = set(work["allowed_property_ids"]) & {
                b["property_id"] for b in spec["properties"]
            }
            if not allowed:
                raise DomainError("EMPTY_ATTACHMENT_SCOPE", "附件没有性质读取权限")
            closed = any(
                row["owner"] == "M03" for row in self.repo.objects(conn, tid, "branch_closure")
            )
        if closed:
            with self.repo.transaction() as conn:
                self.repo.validate_lease(conn, job)
                self.repo.put_object(
                    conn,
                    tid,
                    "coverage",
                    "attachments-" + work_id,
                    1,
                    {
                        "owner": "M05",
                        "work_id": work_id,
                        "state": "partial",
                        "reason": "not_checked_M03_budget_closed",
                    },
                )
                self.repo.finish_job(conn, job)
            return
        dois = sorted(
            {
                doi
                for record in work["records"]
                for doi in record["dois"]
                if not doi.startswith("10.48550/")
            }
        )
        landings = []
        for record in work["records"]:
            for raw in record["raw"].get("links_data", []):
                try:
                    link = loads(raw) if isinstance(raw, str) else raw
                except (ValueError, DomainError):
                    continue
                if not isinstance(link, dict):
                    continue
                if link.get("type") in {"electr", "html"} or link.get("link_type") == "PUB_HTML":
                    url = link.get("url", "").replace("http://", "https://", 1)
                    if url.startswith("https://"):
                        landings.append(url)
        landings += ["https://doi.org/" + doi for doi in dois]
        candidates, gaps, attachments = {}, [], []
        for url in list(dict.fromkeys(landings)):
            try:
                raw, metadata = await self.steps.http(job).request(
                    tid,
                    "M05",
                    "publisher",
                    "GET",
                    url,
                    max_bytes=2 * 1024**2,
                    timeout=30,
                    max_redirects=5,
                    resource_scope="attachment",
                )
                links, refused = official_links(raw, metadata["endpoint"], dois)
                landing = self.app.artifacts.write(raw, "text/html")
                with self.repo.transaction() as conn:
                    self.repo.validate_lease(conn, job)
                    self.app.artifacts.register(conn, tid, work_id + ":official-landing", landing)
                gaps.extend(refused)
                for candidate in links:
                    candidate["association"]["landing_artifact_ref"] = landing["artifact_id"]
                    candidates.setdefault(candidate["url"], candidate)
            except DomainError as exc:
                if exc.code in {
                    "DEFINITION_INVALIDATED",
                    "HTTP_DISPATCH_FORBIDDEN",
                    "LEASE_EXPIRED",
                }:
                    raise
                gaps.append({"url": url, "reason": exc.code})
        # CDS is an official publication-data archive. Search only the selected
        # work's own bibcodes, then require the ReadMe's primary citation before
        # admitting any file. References to this work in another catalog fail.
        archive_links, archive_gaps = await self.archive_candidates(job, work)
        gaps.extend(archive_gaps)
        for candidate in archive_links:
            candidates.setdefault(candidate['url'], candidate)
        readmes = []
        ordered = sorted(
            candidates.items(), key=lambda pair: (pair[1]["format"] != "readme", pair[0])
        )
        for url, candidate in ordered:
            try:
                if candidate.get('acquired'):
                    metadata = candidate['acquired']['metadata']
                    _, path = self.app.artifacts.read_owned(tid, candidate['acquired']['artifact']['artifact_id'])
                    raw = path.read_bytes()
                else:
                    raw, metadata = await self.steps.http(job).request(
                    tid,
                    "M05",
                    "publisher",
                    "GET",
                    url,
                    max_bytes=32 * 1024**2,
                    timeout=90,
                    max_redirects=5,
                    resource_scope="attachment",
                )
                candidate = dict(candidate, format=acquired_format(raw, candidate, metadata))
                if candidate["format"] == "container":
                    found, container_gaps = await self.ingest_container(
                        job,
                        work,
                        allowed,
                        ledger,
                        url,
                        candidate,
                        raw,
                        metadata,
                        None,
                    )
                    attachments.extend(found)
                    gaps.extend(container_gaps)
                    continue
                if candidate['format'] == 'pdf':
                    attachment_id = await self.ingest_pdf(job, work, allowed, url, candidate, raw, metadata)
                    attachments.append(attachment_id)
                    continue
                if candidate["format"] == "readme":
                    if len(raw) > 256 * 1024:
                        raise DomainError("CDS_README_LIMIT", "CDS说明文件过大")
                    raw.decode("utf-8-sig")
                    artifact = self.app.artifacts.write(raw, "text/plain")
                    with self.repo.transaction() as conn:
                        self.repo.validate_lease(conn, job)
                        self.app.artifacts.register(
                            conn, tid, work_id + ":official-readme", artifact
                        )
                    readmes.append(
                        {"artifact": artifact, "url": url, "association": candidate["association"]}
                    )
                    continue
                artifact = self.app.artifacts.write(
                    raw,
                    {
                        "csv": "text/csv",
                        "tsv": "text/tab-separated-values",
                        "fits": "application/fits",
                        "votable": "application/x-votable+xml",
                        "mrt": "text/plain",
                    }[candidate["format"]],
                )
                attachment_id = "attachment-" + digest(
                    {
                        "work_id": work_id,
                        "artifact": artifact["sha256"],
                        "association": candidate["association"],
                    }
                )
                attachment = {
                    "schema_version": "StructuredAttachment/2",
                    "attachment_id": attachment_id,
                    "work_id": work_id,
                    "selected_property_ids": sorted(allowed),
                    "format": candidate["format"],
                    "artifact": artifact,
                    "table_id": attachment_id + "/table",
                    "origin_url": url,
                    "original_filename": PurePosixPath(urlsplit(url).path).name,
                    "readme": next(
                        (
                            item
                            for item in readmes
                            if urlsplit(item["url"]).path.rsplit("/", 1)[0]
                            == urlsplit(url).path.rsplit("/", 1)[0]
                            and urlsplit(item["url"]).netloc == urlsplit(url).netloc
                        ),
                        None,
                    ),
                    "association": candidate["association"],
                    "retrieval": metadata,
                    "actual_work_version": "published_supplement_version_unconfirmed",
                    "selection": ledger["selections"][work_id],
                    "status": "association_verified_format_pending",
                }
                with self.repo.transaction() as conn:
                    self.repo.validate_lease(conn, job)
                    self.app.artifacts.register(conn, tid, attachment_id, artifact)
                    self.repo.put_object(conn, tid, "attachment", attachment_id, 1, attachment)
                    self.repo.enqueue(
                        conn,
                        tid,
                        "M03",
                        "attachment_extract",
                        {
                            "attachment_id": attachment_id,
                            "table_id": attachment["table_id"],
                            "work_id": work_id,
                        },
                    )
                attachments.append(attachment_id)
            except DomainError as exc:
                if exc.code in {
                    "DEFINITION_INVALIDATED",
                    "HTTP_DISPATCH_FORBIDDEN",
                    "LEASE_EXPIRED",
                }:
                    raise
                gaps.append({"url": url, "reason": exc.code})
        with self.repo.transaction() as conn:
            self.repo.validate_lease(conn, job)
            self.repo.put_object(
                conn,
                tid,
                "coverage",
                "attachments-" + work_id,
                1,
                {
                    "owner": "M05",
                    "work_id": work_id,
                    "state": "partial" if gaps else "checked",
                    "attachment_ids": attachments,
                    "checked_landings": list(dict.fromkeys(landings)),
                    "gaps": gaps,
                    "discovery_result": "associated_candidates"
                    if attachments
                    else "candidates_unresolved_or_unavailable" if gaps
                    else "not_found_in_checked_supported_endpoints",
                    "limitations": [
                        "unsupported publisher layouts and container members outside declared limits remain gaps"
                    ],
                },
            )
            self.repo.finish_job(conn, job)

    async def ingest_pdf(self, job, work, allowed, url, candidate, raw, metadata):
        """Read an official supplement, never pretend it is a complete manuscript."""
        from ..documents import maximum_pages
        from ..qualification import qualify_source
        tid = job['task_id']
        artifact = self.app.artifacts.write(raw, 'application/pdf')
        path = self.app.artifacts.path(artifact['relative_path'])
        probe = await self.app.parsers.run('probe_pdf', path, timeout=30)
        aid = 'supplement-pdf-' + digest([work['work_id'], artifact['sha256']])
        with self.repo.read() as conn:
            limit = maximum_pages(self.repo, conn, tid)
            existing = next((s for s in self.repo.objects(conn, tid, 'source') if s['source_id'] == aid), None)
        if existing:
            mention = {'source_id':aid, 'origin_url':url, 'association':candidate['association'], 'retrieval':metadata}
            with self.repo.transaction() as conn:
                self.repo.validate_lease(conn, job)
                self.repo.put_object(conn, tid, 'attachment_mention', 'mention-' + digest(mention), 1, mention)
            return aid
        if limit is not None and probe['page_count'] > limit:
            with self.repo.transaction() as conn:
                self.repo.validate_lease(conn, job)
                self.app.artifacts.register(conn, tid, aid, artifact)
                self.repo.put_object(conn, tid, 'pdf_version_screening', artifact['artifact_id'], 1,
                    {'work_id':work['work_id'], 'attachment_id':aid, 'page_count':probe['page_count'],
                     'maximum_pdf_pages':limit, 'reason':'pdf_physical_page_limit', 'models_scheduled':False})
            raise DomainError('PDF_PHYSICAL_PAGE_LIMIT', '官方补充PDF超过50页，整份不读')
        inspection = await self.app.parsers.run('inspect_pdf', path)
        identity = {'state':'official_attachment_association_verified', 'parent_work_id':work['work_id'],
                    'association':candidate['association'], 'not_a_complete_manuscript':True}
        source, qualification = qualify_source({'source_id':aid, 'kind':'paper', 'work':work,
            'title':[r['titles'] for r in work['records']], 'artifact':artifact, 'identity':identity,
            'parent_work_id':work['work_id'], 'official_supplement':True, 'origin_url':url,
            'version_grade':'unknown', 'association':candidate['association'], 'retrieval':metadata},
            identity=identity, checked_scope=['verified_parent', 'official_supplement_link', 'actual_pdf'],
            version_state='published_supplement_version_unconfirmed')
        with self.repo.transaction() as conn:
            self.repo.validate_lease(conn, job)
            self.app.artifacts.register(conn, tid, aid, artifact)
            self.repo.put_object(conn, tid, 'source', aid, 1, source)
            self.repo.put_object(conn, tid, 'qualification', qualification['qualification_id'], 1, qualification)
            self.repo.put_object(conn, tid, 'document_index', aid, 1, inspection)
            from ..papers.acquisition import initial_core_batches
            for pid in sorted(allowed):
                for pages in initial_core_batches(inspection):
                    self.repo.enqueue(conn, tid, 'M06', 'paper_batch', {'work_id':aid,
                        'read_grant_work_id':work['work_id'], 'property_ids':[pid],
                        'reading_batch_id':digest([aid, pid, pages]), 'core_pages':pages,
                        'artifact_ref':artifact['artifact_id']})
        return aid

    async def archive_candidates(self, job, work):
        from ..catalogs import parse_votable
        from ..catalog_document import readme_url
        from ..official_archive import archive_links

        tid, candidates, gaps = job['task_id'], {}, []
        bibcodes = sorted({record.get('bibcode') for record in work['records']
            if record.get('bibcode') and 'arXiv' not in record['bibcode']})
        seen = set()
        for bibcode in bibcodes:
            url = 'https://vizier.cds.unistra.fr/viz-bin/votable'
            try:
                from ..catalogs import VizierCatalogs
                raw, _ = await VizierCatalogs(self.steps.http(job), owner='M05', service='publisher').request(tid,
                    params={'-source': bibcode, '-meta': '', '-out.max': '0'},
                    max_bytes=4 * 1024**2, timeout=30, resource_scope='attachment')
                metadata_artifact = self.app.artifacts.write(raw, 'application/x-votable+xml')
                with self.repo.transaction() as conn:
                    self.repo.validate_lease(conn, job)
                    self.app.artifacts.register(conn, tid, work['work_id'] + ':cds-metadata', metadata_artifact)
                parsed = parse_votable(raw)
                for resource in parsed['resources']:
                    catalog_id = resource['resource_id']
                    if catalog_id in seen:
                        continue
                    seen.add(catalog_id)
                    tables = [t['table_id'] for t in resource['tables']]
                    readme = readme_url(catalog_id, next(iter(tables), catalog_id + '/_'))
                    data, metadata = await self.steps.http(job).request(tid, 'M05', 'publisher', 'GET', readme,
                        max_bytes=256 * 1024, timeout=30, resource_scope='attachment')
                    artifact = self.app.artifacts.write(data, 'text/plain')
                    with self.repo.transaction() as conn:
                        self.repo.validate_lease(conn, job)
                        self.app.artifacts.register(conn, tid, work['work_id'] + ':cds-readme', artifact)
                    found, rejected = archive_links(data, catalog_id, tables, bibcodes, artifact_ref=artifact['artifact_id'])
                    gaps.extend(rejected)
                    for candidate in found:
                        candidate['association']['discovery_artifact_ref'] = metadata_artifact['artifact_id']
                        if candidate['format'] == 'readme':
                            candidate['acquired'] = {'artifact': artifact, 'metadata': metadata}
                        candidates.setdefault(candidate['url'], candidate)
                if parsed['overflow'] or len(parsed['resources']) > 4:
                    gaps.append({'url': url, 'reason': 'official_archive_catalog_limit', 'bibcode': bibcode})
            except DomainError as exc:
                if exc.code in {'DEFINITION_INVALIDATED', 'HTTP_DISPATCH_FORBIDDEN', 'LEASE_EXPIRED'}:
                    raise
                gaps.append({'url': url, 'bibcode': bibcode, 'reason': exc.code})
        if len(bibcodes) > 4:
            gaps.append({'reason': 'official_archive_bibcode_limit', 'not_checked': bibcodes[4:]})
        return list(candidates.values()), gaps

    async def ingest_container(
        self, job, work, allowed, ledger, url, candidate, raw, metadata, remaining_slots
    ):
        import base64

        tid, work_id = job["task_id"], work["work_id"]
        parent = self.app.artifacts.write(raw, "application/octet-stream")
        with self.repo.transaction() as conn:
            self.repo.validate_lease(conn, job)
            self.app.artifacts.register(conn, tid, work_id + ":official-container", parent)
        from astroquery_ai.runtime.source_resources import SourceResources

        resources = SourceResources(self.repo)
        reservation = resources.reserve_container(job, parent)
        parsed = await self.app.parse_owned(
            tid,
            parent["artifact_id"],
            "structured_archive",
            original_filename=PurePosixPath(urlsplit(url).path).name,
        )
        resources.settle(tid, reservation, parsed["expanded_bytes"])
        manifest_id = "container-manifest-" + digest(
            {"work": work_id, "artifact": parent["sha256"], "association": candidate["association"]}
        )
        manifest = {key: value for key, value in parsed.items() if key != "members"}
        manifest.update(
            work_id=work_id,
            artifact=parent,
            association=candidate["association"],
            retrieval=metadata,
        )
        found, gaps, saved = [], list(parsed["gaps"]), []
        tables = [
            item for item in parsed["members"] if item["format"] not in {"readme", "container"}
        ]
        selected = tables if remaining_slots is None else tables[:remaining_slots]
        gaps.extend(
            {"path": item["path"], "reason": "container_table_selection_limit"}
            for item in ([] if remaining_slots is None else tables[remaining_slots:])
        )
        for member in parsed["members"]:
            if member["format"] not in {"readme", "container"} and member not in selected:
                continue
            payload = base64.b64decode(member["data_base64"], validate=True)
            if member["format"] == "readme":
                try:
                    if len(payload) > 256 * 1024:
                        raise ValueError("readme limit")
                    payload.decode("utf-8-sig")
                except (ValueError, UnicodeError):
                    gaps.append(
                        {"path": member["path"], "reason": "container_readme_size_or_encoding"}
                    )
                    continue
            artifact = self.app.artifacts.write(payload, "application/octet-stream")
            if artifact["sha256"] != member["sha256"]:
                raise DomainError("CONTAINER_MEMBER_HASH", "容器成员与隔离解析回执不一致")
            with self.repo.transaction() as conn:
                self.repo.validate_lease(conn, job)
                self.app.artifacts.register(conn, tid, manifest_id, artifact)
            saved.append(
                {
                    **{key: value for key, value in member.items() if key != "data_base64"},
                    "artifact": artifact,
                }
            )
        manifest["selected_member_hashes"] = [item["sha256"] for item in selected]
        manifest["gaps"] = gaps
        manifest["state"] = "partial" if gaps else parsed["state"]
        with self.repo.transaction() as conn:
            self.repo.validate_lease(conn, job)
            manifest_ref = self.repo.put_object(
                conn, tid, "container_manifest", manifest_id, 1, manifest
            )
        for member in saved:
            if member["format"] in {"readme", "container"}:
                continue
            association = {
                **candidate["association"],
                "container_manifest_ref": manifest_ref,
                "container_artifact_ref": parent["artifact_id"],
                "member_path": member["path"],
                "member_sha256": member["sha256"],
                "parent_chain": member["parent_chain"],
            }
            attachment_id = "attachment-" + digest(
                {"work_id": work_id, "artifact": member["sha256"], "association": association}
            )
            readme = next(
                (
                    item
                    for item in saved
                    if item["format"] == "readme"
                    and item["parent_chain"] == member["parent_chain"]
                    and PurePosixPath(item["path"]).parent == PurePosixPath(member["path"]).parent
                ),
                None,
            )
            attachment = {
                "schema_version": "StructuredAttachment/2",
                "attachment_id": attachment_id,
                "work_id": work_id,
                "selected_property_ids": sorted(allowed),
                "format": member["format"],
                "artifact": member["artifact"],
                "table_id": attachment_id + "/table",
                "origin_url": url,
                "original_filename": PurePosixPath(member["path"]).name,
                "readme": {
                    "artifact": readme["artifact"],
                    "url": url,
                    "association": association,
                    "container_path": readme["path"],
                }
                if readme
                else None,
                "association": association,
                "retrieval": {
                    "kind": "owned_official_container_member",
                    "parent_retrieval": metadata,
                },
                "actual_work_version": "published_supplement_version_unconfirmed",
                "selection": ledger["selections"][work_id],
                "status": "association_verified_format_pending",
            }
            with self.repo.transaction() as conn:
                self.repo.validate_lease(conn, job)
                self.repo.put_object(conn, tid, "attachment", attachment_id, 1, attachment)
                self.repo.enqueue(
                    conn,
                    tid,
                    "M03",
                    "attachment_extract",
                    {
                        "attachment_id": attachment_id,
                        "table_id": attachment["table_id"],
                        "work_id": work_id,
                    },
                )
            found.append(attachment_id)
        return found, gaps


class LocalAttachmentCatalog:
    def __init__(self, application, task_id, attachment):
        self.app, self.task_id, self.attachment = application, task_id, attachment
        self.namespace = None

    async def table_schema(self, task_id, table_id):
        options = self.readme_options()
        result = await self.app.parse_owned(
            task_id,
            self.attachment["artifact"]["artifact_id"],
            "structured_table",
            format=self.attachment["format"],
            table_id=table_id,
            header_only=True,
            **options,
        )
        if options:
            from ..catalog_document import parse_readme
            from astroquery_ai.runtime.codec import digest
            parsed = parse_readme(options['readme_text'], self.attachment['original_filename'].rsplit('.', 1)[0])
            for resource in result["resources"]:
                for table in resource["tables"]:
                    artifact = self.attachment['readme']['artifact']
                    table['catalog_document'] = {
                        'document_ref': 'attachment-readme-' + digest({'attachment': self.attachment['attachment_id'], 'artifact': artifact['sha256']}),
                        'origin_url': self.attachment['readme']['url'], 'state': 'acquired',
                        'artifact_ref': {'id': artifact['artifact_id'], 'version': 1, 'content_sha256': artifact['sha256']},
                        'parsed': {**parsed, 'table_id': table_id}}
                    table["readme_context"] = {
                        "artifact_ref": self.attachment["readme"]["artifact"]["artifact_id"],
                        "text": options["readme_text"][:12000],
                        "truncated": len(options["readme_text"]) > 12000,
                    }
        return result, b"", {"source": "owned_structured_attachment"}

    def readme_options(self):
        if self.attachment["format"] != "mrt" or not self.attachment.get("readme"):
            return {}
        _, path = self.app.artifacts.read_owned(
            self.task_id, self.attachment["readme"]["artifact"]["artifact_id"]
        )
        return {
            "readme_text": path.read_bytes().decode("utf-8-sig"),
            "original_filename": self.attachment["original_filename"],
        }

    async def exact_query(self, task_id, table_id, id_column, identifier, *, datatype="char"):
        alias = self.namespace + " " + identifier if self.namespace else identifier
        result = await self.app.parse_owned(
            task_id,
            self.attachment["artifact"]["artifact_id"],
            "structured_table",
            format=self.attachment["format"],
            table_id=table_id,
            id_column=id_column,
            namespace=self.namespace,
            aliases=[alias],
            **self.readme_options(),
        )
        return result, b"", {"source": "owned_structured_attachment"}

    async def identity_candidates(self, task_id, table_id, id_column, aliases, *, datatype='char', candidate_pattern=None):
        # Parsing without an ID filter preserves source row numbers. The
        # bounded result is interpreted by the same M03 source-ID consumer.
        from ..catalog_identity import navigation_patterns
        patterns = navigation_patterns(aliases)
        result = await self.app.parse_owned(task_id, self.attachment['artifact']['artifact_id'],
            'structured_table', format=self.attachment['format'], table_id=table_id,
            **({'id_column': id_column, 'candidate_patterns': patterns} if patterns else {}),
            **self.readme_options())
        return result, b'', {'source': 'owned_structured_attachment', 'identity_granted_by_search': False}
