"Dynamic VizieR discovery/parsing and exact, namespace-preserving identity."

from __future__ import annotations

from astroquery_ai.science.catalog.identifiers import (
    declared_namespace,
    exact_identifier,
    exact_rows,
    gaia_global_designation,
    identifier_selectors,
    identifier_typography,
    local_identifier,
)

import re

import xml.etree.ElementTree as ET

import unicodedata

from astroquery_ai.runtime.errors import DomainError


def parse_votable(raw: bytes, *, allow_unnamed=False, allow_partial_metadata=False) -> dict:
    if len(raw) > 32 * 1024**2 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise DomainError("UNSAFE_VOTABLE", "表响应大小或XML声明不受支持", 422)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise DomainError("VOTABLE_PARSE_ERROR", "星表响应不是有效VOTable", 502) from exc

    def local(element):
        return element.tag.rsplit("}", 1)[-1]

    if local(root) != "VOTABLE":
        raise DomainError("VOTABLE_PARSE_ERROR", "XML根节点不是VOTABLE", 502)
    infos = [
        {
            "name": node.attrib.get("name"),
            "value": node.attrib.get("value"),
            "text": node.text or "",
        }
        for node in root.iter()
        if local(node) == "INFO"
    ]
    service_errors = [info for info in infos if (
        info['name'] in {'QUERY_STATUS','Error'} and (info['value']=='ERROR' or info['name']=='Error'))]
    missing_catalog = (any((i.get('value') or '').startswith('Table or Catalog not found:') for i in service_errors)
        and not any(local(n)=='TABLE' for n in root.iter()))
    # A successful keyword search may legitimately find no catalogues. The
    # same response to a concrete -source lookup is still an invalid source.
    empty_search = bool(missing_catalog and allow_partial_metadata)
    if missing_catalog and not empty_search:
        raise DomainError('CATALOG_NOT_FOUND','当前来源标识没有对应的目录表',502,
            negative_catalog_lookup=True)
    metadata_hint_only = bool(allow_partial_metadata and service_errors and not empty_search and not any(
        local(n) in {'TR','BINARY','BINARY2','STREAM','FITS'} for n in root.iter()))
    if not metadata_hint_only and not empty_search and any(
        (
            info["name"] in {"QUERY_STATUS", "Error"}
            and (info["value"] == "ERROR" or info["name"] == "Error")
            for info in infos
        )
    ):
        raise DomainError("CATALOG_SERVICE_ERROR", "星表服务返回查询错误", 502)
    overflow = any((info["value"] == "OVERFLOW" for info in infos))
    coordinate_systems = [dict(node.attrib) for node in root.iter() if local(node) == "COOSYS"]
    time_systems = [dict(node.attrib) for node in root.iter() if local(node) == "TIMESYS"]
    from astroquery_ai.science.table_metadata import referenced_context

    resources = []
    for resource in root.iter():
        if local(resource) != "RESOURCE":
            continue
        resource_name = resource.attrib.get("name") or resource.attrib.get("ID")
        if not resource_name and (not allow_unnamed):
            continue
        resource_name = resource_name or "local-resource-" + str(len(resources))
        descriptions = [node.text or "" for node in resource if local(node) == "DESCRIPTION"]
        tables = []
        for table in resource:
            if local(table) != "TABLE":
                continue
            fields = []
            for field in table:
                if local(field) == "FIELD":
                    fields.append(
                        {
                            "name": field.attrib.get("name") or field.attrib.get("ID"),
                            "id": field.attrib.get("ID"),
                            **(
                                {
                                    "ref": field.attrib["ref"],
                                    "reference_context": referenced_context(
                                        field.attrib["ref"], coordinate_systems, time_systems
                                    ),
                                }
                                if field.attrib.get("ref")
                                else {}
                            ),
                            "datatype": field.attrib.get("datatype"),
                            "unit_text": field.attrib.get("unit"),
                            "ucd": field.attrib.get("ucd"),
                            "arraysize": field.attrib.get("arraysize"),
                            "description": " ".join(
                                (node.text or "" for node in field if local(node) == "DESCRIPTION")
                            ),
                            "null": next(
                                (
                                    node.attrib.get("null")
                                    for node in field
                                    if local(node) == "VALUES"
                                ),
                                None,
                            ),
                        }
                    )
            name = table.attrib.get("name") or table.attrib.get("ID")
            if not name and allow_unnamed:
                name = resource_name + "/local-table-" + str(len(tables))
            if not name:
                raise DomainError("ANONYMOUS_TABLE", "数据表缺少稳定标识", 502)
            if any((not field["name"] for field in fields)) or len(
                {field["name"] for field in fields}
            ) != len(fields):
                raise DomainError("VOTABLE_COLUMNS", "表列标识为空或重复", 502)
            rows = []
            for tr in table.iter():
                if local(tr) != "TR":
                    continue
                cells = ["".join(td.itertext()) for td in tr if local(td) == "TD"]
                if len(cells) != len(fields):
                    raise DomainError("VOTABLE_ROW_SHAPE", "表行和列定义数量不一致", 502)
                rows.append({field["name"]: cell for field, cell in zip(fields, cells)})
            tables.append(
                {
                    "table_id": name,
                    "catalog_id": resource_name,
                    "columns": fields,
                    "rows": rows,
                    "description": " ".join(
                        (node.text or "" for node in table if local(node) == "DESCRIPTION")
                    ),
                    "resource_description": " ".join(descriptions),
                    "coordinate_systems": coordinate_systems,
                    "time_systems": time_systems,
                    "binary_data": any(
                        (local(node) in {"BINARY", "BINARY2", "FITS"} for node in table.iter())
                    ),
                }
            )
        resources.append(
            {"resource_id": resource_name, "description": " ".join(descriptions), "tables": tables}
        )
    if metadata_hint_only and not resources:
        raise DomainError('CATALOG_SERVICE_ERROR','目录检索未返回任何可用的元数据',502)
    from urllib.parse import unquote

    metadata_text = "\n".join(
        [i["text"] + " " + str(i["value"] or "") for i in infos]
        + [unquote(" ".join(node.attrib.values())) for node in root.iter() if local(node) == "LINK"]
    )
    bibcodes = sorted(
        set(
            re.findall(
                "(?<![A-Za-z0-9])\\d{4}[A-Za-z&.]{5}[0-9.]{4}[A-Za-z.][0-9.]{4}[A-Za-z](?![A-Za-z0-9])",
                metadata_text,
            )
        )
    )
    return {
        "resources": resources,
        "infos": infos,
        "overflow": overflow or metadata_hint_only,
        **({'search_no_matches': True} if empty_search else {}),
        **({'metadata_service_warnings':service_errors,'metadata_hints_only':True} if metadata_hint_only else {}),
        "publication_hints": bibcodes,
        "response_sha256": __import__("hashlib").sha256(raw).hexdigest(),
    }


class VizierCatalogs:
    def __init__(self, http, *, maximum_attempts=3, owner="M03", service="vizier"):
        self.http = http
        self.owner, self.service = (owner, service)
        if type(maximum_attempts) is not int or not 1 <= maximum_attempts <= 3:
            raise ValueError("VizieR maximum attempts must be within 1..3")
        self.maximum_attempts = maximum_attempts

    @staticmethod
    def validate_response(raw, *, metadata_hints=False):
        """HTTP 200 can carry a VizieR database error, not a usable table.

        Keep the source parser strict for measurements. A protocol failure is
        recoverable at another already-known official node, within route bounds.
        """
        try:
            parse_votable(raw, allow_partial_metadata=metadata_hints)
        except DomainError as exc:
            if exc.code not in {'CATALOG_SERVICE_ERROR', 'VOTABLE_PARSE_ERROR'}:
                raise
            import hashlib
            raise DomainError('SOURCE_PROTOCOL_UNAVAILABLE', '官方表节点返回错误文档',
                protocol_error=exc.code, response_sha256=hashlib.sha256(raw).hexdigest()) from exc

    async def request(self, task_id, **kwargs):
        from astroquery_ai.runtime.run_policy import current_job, catalog_window
        job = current_job.get()
        repo = getattr(getattr(self.http, 'steps', None), 'repo', None)
        legacy = False
        if job and repo:
            with repo.read() as conn:
                window = catalog_window(repo, conn, task_id)
                # A deadline is not a transport version. Only saved historical
                # timed tasks without a dynamic discovery contract use this route.
                legacy = window is not None and not window['policy'].get('discovery_protocol')
        if legacy:
            return await self.legacy_request(task_id, **kwargs)
        from astroquery_ai.runtime.service_routes import ServiceRoutes
        routes = ServiceRoutes(self.http, health_service='vizier')
        endpoints = ('https://vizier.cds.unistra.fr/viz-bin/votable',
                     'https://vizier.cfa.harvard.edu/viz-bin/votable',
                     'https://vizier.idia.ac.za/viz-bin/votable')
        metadata_only=str((kwargs.get('params') or {}).get('-out.max',''))=='0'
        keyword_search = '-words' in (kwargs.get('params') or {})
        capability='votable_search' if keyword_search else 'votable_metadata' if metadata_only else 'votable_data'
        await routes.probe(task_id, self.owner, self.service, capability, endpoints,
            {'-words':'Cepheid','-meta':'','-meta.max':'1','-out.max':'0'} if keyword_search else
            {'-source': 'I/239/hip_main', '-out.max': '0' if metadata_only else '1', '-out': 'HIP'})
        kwargs.setdefault('timeout', 30)
        kwargs.setdefault('connect_timeout', 5)
        kwargs.setdefault('read_timeout', 20)
        return await routes.request(task_id, self.owner, self.service, capability, endpoints, 'GET',
            validate_response=lambda raw:self.validate_response(raw, metadata_hints=keyword_search), **kwargs)

    async def legacy_request(self, task_id, **kwargs):
        import time
        import asyncio

        deadline = time.monotonic() + min(30, kwargs.pop("timeout", 30))
        history = []
        endpoints = (
            "https://vizier.cds.unistra.fr/viz-bin/votable",
            "https://vizier.cfa.harvard.edu/viz-bin/votable",
            "https://vizier.idia.ac.za/viz-bin/votable",
        )
        from astroquery_ai.runtime.run_policy import current_job, CATALOG_JOBS, endpoint_cooling, claim_table_repair
        scoped_job = current_job.get()
        scoped = bool(scoped_job and scoped_job['kind'] in CATALOG_JOBS)
        repo = getattr(getattr(self.http, 'steps', None), 'repo', None)
        if scoped:
            # This official route already has real successful-source evidence.
            endpoints = (endpoints[2], endpoints[0], endpoints[1])
        preferences = getattr(self.http, "endpoint_preferences", {})
        preferred = preferences.get((task_id, "vizier_asu"))
        if preferred in endpoints:
            endpoints = (preferred, *(e for e in endpoints if e != preferred))
        if scoped and repo:
            endpoints = tuple(e for e in endpoints if not endpoint_cooling(repo, task_id, self.service, e))
        attempts = min(self.maximum_attempts, 2 if scoped else 3, len(endpoints))
        for index in range(attempts):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if index and scoped and repo and not claim_table_repair(repo, scoped_job):
                break
            try:
                raw, metadata = await self.http.request(
                    task_id,
                    self.owner,
                    self.service,
                    "GET",
                    endpoints[index],
                    timeout=max(0.01, remaining / (attempts - index)),
                    connect_timeout=5,
                    read_timeout=20,
                    **kwargs,
                )
                self.validate_response(raw, metadata_hints='-words' in (kwargs.get('params') or {}))
                metadata["prior_endpoint_failures"] = history
                preferences[task_id, "vizier_asu"] = endpoints[index]
                return (raw, metadata)
            except DomainError as exc:
                retryable = exc.code in {"SOURCE_HTTP_TIMEOUT", "SOURCE_TRANSPORT_ERROR", "SOURCE_PROTOCOL_UNAVAILABLE"} or (
                    exc.code == "SOURCE_HTTP_ERROR"
                    and (
                        exc.details.get("provider_status") in {404, 429}
                        or (exc.details.get("provider_status") or 0) >= 500
                    )
                )
                if not retryable:
                    raise
                history.append({"endpoint": endpoints[index], "reason": exc.code})
                if index + 1 < attempts:
                    await asyncio.sleep(
                        min(1 if index == 0 else 3, max(0, deadline - time.monotonic()))
                    )
        raise DomainError(
            "CATALOG_ENDPOINTS_UNAVAILABLE", "星表入口有界重试后仍不可用", attempts=history
        )

    async def discover(
        self,
        task_id: str,
        target: dict,
        bindings: list[dict],
        family_concepts: list[str],
        *,
        cached=None,
        on_response=None,
        active_seconds=None,
        expressions=None,
        expand_catalogs=True,
        caps=(100, 300),
    ):
        expressions = expressions if expressions is not None else list(
            dict.fromkeys([target["main_id"], *target["aliases"][:8], *family_concepts[:16]])
        )
        import time

        started = time.monotonic()
        cached = {(r["expression"], r["cap"]): r for r in cached or []}
        results = []
        expanded_catalogs = set()
        for expression in expressions:
            for cap in caps:
                prior = cached.get((expression, cap))
                if prior:
                    result = prior
                else:
                    remaining = (
                        45
                        if active_seconds is None
                        else active_seconds - (time.monotonic() - started)
                    )
                    result = {
                        "expression": expression,
                        "cap": cap,
                        "raw": None,
                        "metadata": {},
                        "parsed": {"resources": [], "publication_hints": [], "overflow": False},
                    }
                    if remaining <= 0:
                        result.update(
                            coverage_state="not_checked", reason="metadata_active_time_limit"
                        )
                    else:
                        try:
                            raw, metadata = await self.request(
                                task_id,
                                params={
                                    "-words": expression,
                                    "-meta": "",
                                    "-meta.max": str(cap),
                                    "-obsolete": "",
                                    "-out.max": "0",
                                },
                                max_bytes=16 * 1024**2,
                                timeout=min(45, remaining),
                            )
                            parsed = parse_votable(raw, allow_partial_metadata=True)
                            result.update(
                                raw=raw,
                                metadata=metadata,
                                parsed=parsed,
                                coverage_state="truncated_or_unknown"
                                if parsed["overflow"] or len(parsed["resources"]) >= cap
                                else "complete_for_expression",
                                **({'reason':'no_matching_catalogues'} if parsed.get('search_no_matches') else {}),
                            )
                        except DomainError as exc:
                            if exc.code in {
                                "HTTP_DISPATCH_FORBIDDEN",
                                "DEFINITION_INVALIDATED",
                                "STALE_GENERATION",
                            }:
                                raise
                            result.update(coverage_state="failed", reason=exc.code)
                    if on_response:
                        await on_response(result)
                results.append(result)
                parsed = result["parsed"]
                for resource in parsed["resources"]:
                    if not expand_catalogs:
                        continue
                    catalog = resource["resource_id"]
                    if resource["tables"] or catalog in expanded_catalogs:
                        continue
                    expanded_catalogs.add(catalog)
                    expression_key = "catalog-metadata:" + catalog
                    child = cached.get((expression_key, 0))
                    if child is None:
                        remaining = (
                            45
                            if active_seconds is None
                            else active_seconds - (time.monotonic() - started)
                        )
                        child = {
                            "expression": expression_key,
                            "cap": 0,
                            "raw": None,
                            "metadata": {},
                            "discovered_catalog_id": catalog,
                            "parent_expression": expression,
                            "parsed": {"resources": [], "publication_hints": [], "overflow": False},
                        }
                        if remaining <= 0:
                            child.update(
                                coverage_state="not_checked", reason="metadata_active_time_limit"
                            )
                        else:
                            try:
                                raw, metadata = await self.request(
                                    task_id,
                                    params={
                                        "-source": catalog,
                                        "-meta.all": "1",
                                        "-out.all": "1",
                                        "-out.max": "0",
                                    },
                                    max_bytes=8 * 1024**2,
                                    timeout=min(30, remaining),
                                )
                                table_metadata = parse_votable(raw)
                                child.update(
                                    raw=raw,
                                    metadata=metadata,
                                    parsed=table_metadata,
                                    coverage_state="truncated_or_unknown"
                                    if table_metadata["overflow"]
                                    else "complete_for_expression",
                                )
                            except DomainError as exc:
                                if exc.code in {
                                    "HTTP_DISPATCH_FORBIDDEN",
                                    "DEFINITION_INVALIDATED",
                                    "STALE_GENERATION",
                                }:
                                    raise
                                child.update(coverage_state="failed", reason=exc.code)
                        if on_response:
                            await on_response(child)
                    results.append(child)
                if len(parsed["resources"]) < cap and (not parsed["overflow"]):
                    break
        return results

    async def table_schema(self, task_id, table_id):
        raw, metadata = await self.request(
            task_id,
            params={"-source": table_id, "-meta.all": "1", "-out.all": "1", "-out.max": "0"},
            max_bytes=8 * 1024**2,
        )
        return (parse_votable(raw), raw, metadata)

    async def exact_query(
        self, task_id: str, table_id: str, id_column: str, identifier: str, *, datatype="char"
    ):
        if any((ch in id_column for ch in "\r\n&=")) or not table_id or (not identifier):
            raise DomainError("INVALID_CATALOG_SELECTOR", "星表查询选择器无效", 422)
        numeric = datatype in {"unsignedByte", "short", "int", "long", "float", "double"}
        if numeric and (
            not re.fullmatch("[+-]?\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?", identifier, flags=re.ASCII)
        ):
            raise DomainError(
                "INVALID_CATALOG_SELECTOR", "数值标识列只能查询已限定命名空间的数值字面量", 422
            )
        selector = ("=" if numeric else "==") + identifier
        return await self.selected_rows(task_id, table_id, {id_column: selector})

    async def selected_rows(self, task_id, table_id, selectors=None):
        """Expand a truncated, already-scoped row query; retain the final limit.

        Unfiltered use is reserved for a separately evidenced single-object
        table. This never grants identity from position or from a row count.
        """
        history = []
        for cap in (1000, 10000, 50000):
            raw, metadata = await self.request(task_id,
                params={'-source':table_id, **(selectors or {}), '-out.all':'1', '-out.max':str(cap)},
                max_bytes=32 * 1024**2)
            parsed = parse_votable(raw)
            history.append({'limit':cap, 'response_sha256':parsed['response_sha256'],
                            'overflow':parsed['overflow']})
            if not parsed['overflow']:
                break
        return parsed, raw, {**metadata, 'row_query_limits':history,
                             'row_query_complete':not parsed['overflow']}

    async def identity_candidates(
        self, task_id, table_id, id_column, aliases, *, datatype="char", candidate_pattern=None
    ):
        """Retrieve possible printed IDs; patterns do not establish identity.

        ASU char pattern syntax is documented in vizHelp/cst.htx. Numeric
        tokens come only from frozen aliases; no coordinate/nearest fallback.
        An overflow remains explicit and is never a negative completeness claim.
        """
        from astroquery_ai.science.catalog.identifiers import navigation_patterns

        if any((ch in id_column for ch in "\r\n&=")) or not table_id:
            raise DomainError("INVALID_CATALOG_SELECTOR", "候选标识列无效", 422)
        params = {"-source": table_id, "-out.all": "1", "-out.max": "1000"}
        patterns = navigation_patterns(aliases) if datatype in {"char", "unicodeChar"} else []
        if candidate_pattern is not None and candidate_pattern not in patterns:
            raise DomainError("INVALID_CATALOG_SELECTOR", "候选导航模式不属于已核实标识", 422)
        pattern = candidate_pattern or next(iter(patterns), None)
        if pattern:
            params[id_column] = "~" + pattern
        raw, metadata = await self.request(task_id, params=params, max_bytes=32 * 1024**2)
        parsed = parse_votable(raw)
        return (
            parsed,
            raw,
            {**metadata, "identity_candidate_query": params, "identity_granted_by_search": False},
        )
