"""Existing settings HTTP routes; business services retain authority."""

from __future__ import annotations

from fastapi import Request

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.runtime.paths import knowledge_content_root


def register(app, application, scheduler):

    @app.get("/api/health")
    def health():
        return {"status": "ok", "runtime": "persistent-1", "release_ready": False,
                "scientific_startup": getattr(app.state, 'scientific_startup', 'preparing')}

    @app.get("/api/knowledge-content")
    def knowledge_content(otype: str = "Psr"):
        try:bound=application.knowledge.load()
        except DomainError:bound=None
        if bound and bound['manifest']['schema_version']=='insight-knowledge/3':
            from astroquery_ai.runtime.codec import digest
            author=bound['author'];types=sorted({b['otype'] for b in author['bindings']})
            if otype not in types:raise DomainError('KNOWLEDGE_OTYPE_OUTSIDE_SCOPE','该类型不在作者内容范围内',422)
            entries=[]
            for entry in author['entries']:
                if otype not in entry['otypes']:continue
                claims=[]
                for i,block in enumerate(entry['blocks']):
                    sources=[bound['sources'][sid] for sid in block['source_ids']]
                    claims.append({'claim_id':'kb-block-'+digest([bound['manifest']['content_sha256'],entry['entry_id'],i]),
                        'statement_zh':block['text'],'basis_label':'作者知识整理' if block['basis']=='author_knowledge' else '来源已核读',
                        'source_evidence':[{'source':{'identity':{'title':s['title'],'url':s['url']},'read_level':s['verification']},
                            'evidence':{'evidence_id':s['source_id'],'locator':s['locator'],'excerpt':s['support_note'],
                                'limitations':'进一步阅读，不能冒充核读' if s['verification']=='reference_only' else '保留作者来源标签，不是独立科学审定'}} for s in sources]})
                entries.append({'entry_id':entry['entry_id'],'title':entry['title'],'conditions_zh':'；'.join(entry['conditions']),
                    'limitations_zh':'适用条件还在各段科学正文中；空条件数组不代表无条件通用。','uncertainty_notes':'见正文误差与限制段落。','claims':claims})
            return {'schema_version':'knowledge-content-preview/1','content_release_ref':{
                'id':bound['manifest']['release_id'],'content_hash':bound['manifest']['content_sha256']},
                'otype':otype,'available_types':types,'status':'unbound_preview','target_applicability':'not_established',
                'runtime_authorized':False,'entries':entries}
        from astroquery_ai.science.knowledge_content import KnowledgeContent

        reader = KnowledgeContent()
        release = reader.load(knowledge_content_root())
        return reader.preview(release, otype)

    @app.get("/api/library-status")
    def library_status(view: str = 'verified'):
        if view == 'summary':
            from astroquery_ai.application.library_summary import installed_summary
            return installed_summary(application)
        from astroquery_ai.science.knowledge_content import KnowledgeContent

        try:
            release = application.registry.load()
            manifest = release['manifest']
            registry = {'state': 'available', 'release_id': manifest['release_id'],
                        'content_sha256': manifest['content_sha256'],
                        'counts': manifest.get('counts', {})}
        except DomainError as exc:
            registry = {'state': 'unavailable', 'reason': exc.code}

        try:
            content = KnowledgeContent().load(knowledge_content_root())["report"]
        except DomainError as exc:
            content = {"state": "unavailable", "reason": exc.code}
        try:
            bound = application.knowledge.load()
            bindings = {'state': 'available', 'release_id': bound['manifest']['release_id'],
                        'registry_ref': bound['manifest']['registry_release_ref'],
                        'bindings': len(bound['data']['bindings'])}
            if bound['manifest']['schema_version']=='insight-knowledge/3':
                blocks=[b for e in bound['author']['entries'] for b in e['blocks']]
                content={'state':'available','entries':len(bound['author']['entries']),
                    'types':bound['manifest']['counts']['otypes'],
                    'source_verified_claims':sum(b['basis']=='source_checked' for b in blocks),
                    'author_knowledge_claims':sum(b['basis']=='author_knowledge' for b in blocks),
                    'release_id':bound['manifest']['release_id'],'content_sha256':bound['manifest']['content_sha256']}
        except DomainError as exc:
            bindings = {'state': 'unavailable', 'reason': exc.code}
        return {
            "registry": registry,
            "knowledge_content": content,
            "knowledge_bindings": bindings,
            "runtime_profiles": {
                owner: application._profile_state(owner)
                for owner in ("M01", "M03", "M04", "M06", "M08", "M11")
            },
        }

    @app.get("/api/config")
    def config():
        result = application.configuration.public()
        result.update(version="3.0.0-dev", output_dir=str(application.root / "artifacts"))
        result["runtime_profiles"] = {owner: application._profile_state(owner) for owner in ("M01","M03","M04","M06","M08","M11")}
        result["profile_readiness"] = "validated" if all(state == "validated" for state in result["runtime_profiles"].values()) else "not_validated"
        result["configured"] = {key.upper(): value for key, value in result["configured"].items()}
        result["runtime_configured"] = {
            key.upper(): value for key, value in result["runtime_configured"].items()
        }
        return result

    @app.put("/api/config")
    async def save_config(request: Request):
        if request.headers.get("x-requested-with") != "AstroQuery":
            raise DomainError("CONFIG_WRITE_HEADER", "配置写入缺少客户端标识", 403)
        body = await request.json()
        if set(body) != {"expected_revision", "values"}:
            raise DomainError("INVALID_CONFIG_REQUEST", "配置写入协议无效", 422)
        application.configuration.save(body["values"], body["expected_revision"])
        if not {'dashscope_base_url','dashscope_api_key'} & set(body['values']):
            application.configuration.activate()
        return config()

    @app.post("/api/config/test-and-apply")
    async def apply_config(request: Request):
        if request.headers.get('x-requested-with') != 'AstroQuery':
            raise DomainError('CONFIG_WRITE_HEADER', '配置写入缺少客户端标识', 403)
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {'expected_revision','values'}:
            raise DomainError('INVALID_CONFIG_REQUEST', '配置写入协议无效', 422)
        from astroquery_ai.runtime.connections import test_and_apply
        await test_and_apply(application, body['values'], body['expected_revision'])
        return config()

    @app.get("/api/budget")
    def budget():
        return application.budget.summary()
