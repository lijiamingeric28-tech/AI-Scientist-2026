"science: catalog: discovery.py operations; existing transactions and decisions retained."

from __future__ import annotations

from astroquery_ai.runtime.codec import digest

from astroquery_ai.science.catalogs import VizierCatalogs, parse_votable


def discovered_schema(self, tid, payload):
    """Reuse complete, owned discovery metadata, never a search snippet.

    The catalog-metadata request already asks for every concrete FIELD.
    Re-fetching the same zero-row schema adds no evidence and can fail for
    auxiliary tables even though their real schema is already held.
    """
    artifact = payload.get("discovery_artifact")
    if not artifact:
        return None
    with self.repo.read() as conn:
        saved = next(
            (
                r
                for r in self.repo.objects(conn, tid, "catalog_response")
                if r.get("artifact") == artifact
                and r.get("expression", "").startswith("catalog-metadata:")
                and (r.get("coverage_state") == "complete_for_expression")
            ),
            None,
        )
    if saved is None:
        return None
    _, path = self.app.artifacts.read_owned(tid, artifact["artifact_id"])
    raw = path.read_bytes()
    schema = parse_votable(raw)
    tables = [
        t
        for resource in schema["resources"]
        for t in resource["tables"]
        if t["table_id"] == payload["table_id"]
    ]
    if len(tables) != 1 or not tables[0]["columns"]:
        return None
    return (
        schema,
        raw,
        {**saved["metadata"], "schema_reused_from_discovery_artifact": artifact["artifact_id"]},
    )


async def discover_catalogs(self, job):
    tid = job["task_id"]
    pilot = getattr(self.app, "pilot", None)
    pilot = pilot if pilot and pilot.applies(tid) else None
    with self.repo.read() as conn:
        spec = self.spec(conn, tid)
    release = self.app.registry.load(spec["registry_release"]["id"])
    families = {f["family_id"]: f for f in release["data"]["families"]}
    concepts = list(
        dict.fromkeys(
            (
                term
                for binding in spec["properties"]
                for term in families[binding["definition"]["family_id"]]["search_concepts"]
            )
        )
    )
    with self.repo.read() as conn:
        previous = [
            r
            for r in self.repo.objects(conn, tid, "catalog_response")
            if r["job_id"] == job["job_id"] and r.get("artifact")
        ]
    elapsed = sum((r["metadata"].get("elapsed_seconds", 0) for r in previous))

    async def commit_response(result):
        artifact = (
            self.app.artifacts.write(result["raw"], "application/x-votable+xml")
            if result["raw"] is not None
            else None
        )
        saved = {
            **{k: v for k, v in result.items() if k != "raw"},
            "artifact": artifact,
            "job_id": job["job_id"],
        }
        key = "catalog-response-" + digest(
            {"job": job["job_id"], "expression": result["expression"], "cap": result["cap"]}
        )
        with self.repo.transaction() as conn:
            self.repo.validate_lease(conn, job)
            existing = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='catalog_response' AND object_id=? AND version=1", (tid, key)).fetchone()
            if existing:
                from astroquery_ai.runtime.codec import loads
                result['artifact'] = loads(existing['payload']).get('artifact')
                return  # A replay retains the original response and metadata.
            if artifact:
                self.app.artifacts.register(conn, tid, key, artifact)
            self.repo.put_object(conn, tid, "catalog_response", key, 1, saved)
        result["artifact"] = artifact

    if spec.get('run_policy') and not pilot:
        from .selection import bounded_discovery
        await bounded_discovery(self, job, spec, concepts, previous, commit_response)
        return
    results = await VizierCatalogs(self.steps.http(job)).discover(
        tid,
        spec["target"],
        spec["properties"],
        concepts,
        cached=previous,
        on_response=commit_response,
        active_seconds=max(0, pilot.scope["catalog_discovery_active_seconds"] - elapsed)
        if pilot
        else None,
    )
    tables = {}
    hints = {}
    with self.repo.transaction() as conn:
        self.repo.validate_lease(conn, job)
        for index, response in enumerate(results):
            artifact = response.get("artifact")
            if artifact:
                self.app.artifacts.register(conn, tid, job["job_id"], artifact)
            self.repo.put_object(
                conn,
                tid,
                "coverage",
                "catalog-expression-"
                + digest({"expression": response["expression"], "cap": response["cap"]}),
                1,
                {
                    "owner": "M03",
                    "expression": response["expression"],
                    "state": response["coverage_state"],
                    "response_ref": artifact["artifact_id"] if artifact else None,
                    "reason": response.get("reason"),
                },
            )
            for identifier in response["parsed"].get("publication_hints", []):
                if identifier not in hints:
                    hints[identifier] = {
                        "hint_id": "catalog-hint-"
                        + digest({"id": identifier, "artifact": artifact["artifact_id"]}),
                        "publication_identifiers": [identifier],
                        "metadata_artifact_ref": artifact["artifact_id"],
                        "origin": "independent_catalog_metadata",
                        "locator": "VOTable INFO/LINK",
                        "expression": response["expression"],
                    }
            for resource in response["parsed"]["resources"]:
                for table in resource["tables"]:
                    tables.setdefault(
                        table["table_id"],
                        {
                            "table_id": table["table_id"],
                            "resource_id": resource["resource_id"],
                            "description": resource["description"],
                            "discovery_artifact": artifact,
                        },
                    )
        if pilot:
            seed_id = pilot.source_pair["table"]
            tables = {
                seed_id: {
                    "table_id": seed_id,
                    "resource_id": seed_id.rsplit("/", 1)[0],
                    "description": "性质定义资料中已核验的来源种子；隔离试运行",
                    "discovery_artifact": None,
                    "origin": {
                        "kind": "registry_seed",
                        "source_pair_hash": pilot.source_pair_hash,
                        "candidate_manifest_hash": pilot.scope["projection_receipt"][
                            "source_package_manifest_hash"
                        ],
                    },
                },
                **tables,
            }
        selected_tables = (
            list(tables.values())[: pilot.scope["maximum_catalog_tables"]]
            if pilot
            else list(tables.values())
        )
        if pilot and len(tables) > len(selected_tables):
            self.repo.put_object(
                conn,
                tid,
                "coverage",
                "pilot-catalog-table-cap",
                1,
                {
                    "owner": "M03",
                    "state": "partial",
                    "reason": "isolated_pilot_table_cap",
                    "not_checked_table_ids": list(tables)[len(selected_tables) :],
                },
            )
        for table in selected_tables:
            self.repo.enqueue(conn, tid, "M03", "catalog_extract", table)
        checkpoint = {
            "checkpoint_id": "catalog-checkpoint-" + job["job_id"],
            "task_id": tid,
            "spec_hash": spec["spec_hash"],
            "hints": [hints[key] for key in sorted(hints)],
            "state": "closed_partial"
            if any((r["coverage_state"] != "complete_for_expression" for r in results))
            else "closed_complete",
            "policy": {"maximum_identifiers": None, "maximum_active_seconds": None},
            "semantic_read_granted": False,
        }
        self.repo.put_object(
            conn, tid, "catalog_checkpoint", checkpoint["checkpoint_id"], 1, checkpoint
        )
        self.repo.producer(
            conn,
            tid,
            "catalog_hints",
            close_reason="metadata_checkpoint_closed",
            watermark=len(results),
        )
        self.repo.producer(
            conn, tid, "catalog_discovery", close_reason="expressions_closed", watermark=len(tables)
        )
        self.repo.finish_job(conn, job)
