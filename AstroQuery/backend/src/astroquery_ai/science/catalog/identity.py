"science: catalog: identity.py operations; existing transactions and decisions retained."

from __future__ import annotations

from pydantic import ValidationError

from astroquery_ai.runtime.codec import canonical, digest, content_hash

from astroquery_ai.runtime.errors import DomainError


async def interpret_identity_rows(self, job, spec, table, id_column, input_format, artifact):
    """One bounded row-semantic step; reused by catalogs and official tables."""
    from astroquery_ai.science.catalog_identity import (
        identity_prompt,
        checked_identities,
        checked_table_identity_limitation,
        identity_protocol_repair,
        VERSION,
    )
    from astroquery_ai.runtime.calls import input_upper_bound

    pending = [
        list(range(i, min(i + 32, len(table["rows"])))) for i in range(0, len(table["rows"]), 32)
    ]
    with self.repo.read() as conn:
        prior_checks = self.repo.objects(conn, job["task_id"], "catalog_identity_interpretation")
    results, attempts = ([], {})
    while pending:
        indices = pending.pop(0)
        prompt, spans = identity_prompt(spec["target"], table, table["rows"], indices, id_column)
        messages = [{"role": "user", "content": canonical(prompt).decode()}]
        if input_upper_bound(messages) > 48000:
            if len(indices) == 1:
                raise DomainError(
                    "CATALOG_IDENTITY_CONTEXT_TOO_LARGE", "单行完整身份依据超出已验证请求能力"
                )
            middle = len(indices) // 2
            pending[0:0] = [indices[:middle], indices[middle:]]
            continue
        root_id = (
            job["job_id"]
            + ":source-identity:"
            + digest({"source": artifact["sha256"], "rows": indices, "input": digest(prompt)})
        )

        async def ask(messages):
            return await self.steps.model(
                job,
                task_id=job["task_id"],
                owner="M03",
                root_id=root_id,
                messages=messages,
                job=job,
                purpose="production",
                root_limit=2,
                profile=self.model_profile(
                    "M03",
                    source_format=input_format,
                    operation="catalog_identity",
                    version=VERSION,
                    max_images=0,
                    max_input_tokens=48000,
                    wall_seconds=60,
                    inactivity_seconds=45,
                ),
            )

        prior = next(
            (
                p
                for p in prior_checks
                if p.get("input_hash") == digest(prompt)
                and p.get("source_artifact", {}).get("sha256") == artifact["sha256"]
                and p.get("response")
                and (p.get("target_hash") == content_hash(spec["target"]))
                and (p.get("validator_version") == VERSION)
            ),
            None,
        )
        response, receipt = (
            (prior["response"], prior["attempt_ref"]) if prior else await ask(messages)
        )
        try:
            limitation=checked_table_identity_limitation(response,table,id_column,spans)
            checked = checked_identities(
                response, spec["target"], table, table["rows"], indices, id_column, spans
            )
        except (ValidationError, DomainError) as exc:
            if isinstance(exc, DomainError) and exc.code not in {"CATALOG_IDENTITY_RESPONSE_SCOPE",'CATALOG_IDENTITY_LIMITATION_SCOPE'}:
                raise
            limitation=None
            checked = [
                {"row": i, "state": "unresolved", "reason": "source_identity_response_schema"}
                for i in indices
            ]
        repair = None if limitation else identity_protocol_repair(prompt, response, checked)
        if repair:
            repaired_messages = [{"role": "user", "content": canonical(repair).decode()}]
            if input_upper_bound(repaired_messages) > 48000:
                repair["protocol_repair"].pop("previous_untrusted_response", None)
                repaired_messages = [{"role": "user", "content": canonical(repair).decode()}]
            if input_upper_bound(repaired_messages) <= 48000:
                response, receipt = await ask(repaired_messages)
                limitation=checked_table_identity_limitation(response,table,id_column,spans)
                checked = checked_identities(
                    response, spec["target"], table, table["rows"], indices, id_column, spans
                )
        if limitation:
            unexamined=[*indices,*(i for group in pending for i in group)]
            saved_limit={'table_id':table['table_id'],'source_artifact':artifact,
                'target_hash':content_hash(spec['target']),'limitation':limitation,'attempt_ref':receipt,
                'validator_version':VERSION,'unexamined_row_indices':unexamined,
                'state':'cross_identification_required','target_absence_claimed':False}
            with self.repo.transaction() as conn:
                self.repo.validate_lease(conn,job)
                ref=self.repo.put_object(conn,job['task_id'],'catalog_identity_limitation',
                    'identity-limit-'+digest(saved_limit),1,saved_limit)
            checked=[{'row':i,'state':'unresolved','reason':'source_cross_identification_missing',
                'row_examined':False,'source_scope_ref':ref} for i in unexamined]
            pending.clear()
        results.extend(checked)
        attempts.update({i: receipt for i in indices})
        saved = {
            "table_id": table["table_id"],
            "source_artifact": artifact,
            "target_hash": content_hash(spec["target"]),
            "input_hash": digest(prompt),
            "response": response,
            "checks": checked,
            "attempt_ref": receipt,
            "validator_version": VERSION,
        }
        with self.repo.transaction() as conn:
            self.repo.validate_lease(conn, job)
            self.repo.put_object(
                conn,
                job["task_id"],
                "catalog_identity_interpretation",
                "identity-" + digest(saved),
                1,
                saved,
            )
    return (results, attempts)
