"""Exact-name SIMBAD identity resolution with response evidence, never nearest."""

import math
from astroquery_ai.runtime.codec import loads, digest, new_id, content_hash
from astroquery_ai.runtime.errors import DomainError


class SimbadIdentity:
    def __init__(self, http, artifacts):
        self.http, self.artifacts = http, artifacts

    async def resolve(self, task_id: str, mention: str) -> dict:
        if not mention.strip() or len(mention) > 256 or any(c in mention for c in "\r\n\0"):
            raise DomainError("INVALID_TARGET_NAME", "天体名称无效", 422)
        literal = mention.replace("'", "''")
        astrometry_fields = ['coo_err_maj', 'coo_err_min', 'coo_err_angle', 'coo_bibcode',
            'pmra', 'pmdec', 'pm_err_maj', 'pm_err_min', 'pm_err_angle', 'pm_bibcode',
            'plx_value', 'plx_err', 'plx_bibcode', 'rvz_radvel', 'rvz_err', 'rvz_bibcode']
        query = (
            "SELECT TOP 32 b.oid, b.main_id, b.otype, b.ra, b.dec, "
            + ', '.join('b.' + name for name in astrometry_fields) + ", i.ids, t.otypes "
            "FROM basic AS b JOIN ident AS n ON n.oidref=b.oid "
            "LEFT JOIN ids AS i ON i.oidref=b.oid LEFT JOIN alltypes AS t ON t.oidref=b.oid " + f"WHERE n.id='{literal}'"
        )
        from astroquery_ai.runtime.service_routes import ServiceRoutes
        endpoints = ('https://simbad.cfa.harvard.edu/simbad/sim-tap/sync',
                     'https://simbad.cds.unistra.fr/simbad/sim-tap/sync')
        routes = ServiceRoutes(self.http)
        protocol = 'tap'
        try:
            raw, metadata = await routes.request(task_id, 'M01', 'simbad',
                'identity_tap', endpoints, 'POST',
                data={'request':'doQuery', 'lang':'adql', 'format':'json', 'query':query},
                max_bytes=2*1024**2, timeout=12, connect_timeout=5, read_timeout=12)
            response = loads(raw)
            adapter_version, media_type = 'simbad-tap-3', 'application/json'
        except DomainError as exc:
            if exc.code != 'IDENTITY_ENDPOINTS_UNAVAILABLE':
                raise  # No mirror/alternate-protocol evasion of a rate refusal.
            from urllib.parse import quote
            from .simbad_protocols import sesame_view
            # Existing SIMBAD-only Sesame adapter is a protocol fallback at the
            # same official Harvard site, not an independent mirror vote.
            url = 'https://vizier.cfa.harvard.edu/viz-bin/nph-sesame/-oxpI/~S?' + quote(mention)
            raw, metadata = await routes.request(task_id, 'M01', 'simbad',
                'identity_sesame', [url], 'GET', max_bytes=2*1024**2,
                timeout=12, connect_timeout=5, read_timeout=12)
            response = sesame_view(raw, mention)
            adapter_version, media_type, protocol = 'simbad-sesame-1', 'application/xml', 'sesame'
            metadata['tap_failures'] = exc.details.get('attempts', [])
            metadata['prior_endpoint_failures'] = [*metadata['tap_failures'], *metadata.get('prior_endpoint_failures', [])]
        metadata = {**metadata, 'identity_protocol':protocol, 'authority':'SIMBAD',
                    'adapter_version':adapter_version}
        if (
            not isinstance(response, dict)
            or not isinstance(response.get("metadata"), list)
            or not isinstance(response.get("data"), list)
        ):
            raise DomainError("IDENTITY_PROVIDER_SCHEMA", "SIMBAD返回结构不完整", 502)
        if any(not isinstance(c, dict) or not isinstance(c.get('name'), str) or not c['name'].strip()
                for c in response['metadata']):
            raise DomainError('IDENTITY_PROVIDER_SCHEMA', 'SIMBAD字段元数据无效')
        names = [c['name'].lower() for c in response['metadata']]
        if len(set(names)) != len(names):
            raise DomainError('IDENTITY_PROVIDER_SCHEMA', 'SIMBAD字段名重复')
        if not {"oid", "main_id", "otype", "ra", "dec", "ids"} <= set(names):
            raise DomainError("IDENTITY_PROVIDER_SCHEMA", "SIMBAD缺少身份必需字段", 502)
        artifact = self.artifacts.write(raw, media_type)
        targets, astrometric_evidence, seen = [], [], set()
        for row in response["data"]:
            if not isinstance(row, list) or len(row) != len(names):
                raise DomainError("IDENTITY_PROVIDER_SCHEMA", "SIMBAD身份行字段不匹配", 502)
            values = dict(zip(names, row))
            if (
                not isinstance(values["main_id"], str)
                or not values["main_id"].strip()
                or not isinstance(values["otype"], str)
                or not values["otype"].strip()
            ):
                raise DomainError("IDENTITY_PROVIDER_SCHEMA", "SIMBAD缺少规范名称或当前主型", 502)
            if values["oid"] in seen:
                continue
            seen.add(values["oid"])
            target_id = "simbad-" + digest({"oid": str(values["oid"])})
            evidence_id = "identity-" + digest(
                {"artifact": artifact["sha256"], "oid": str(values["oid"])}
            )
            if values['ids'] is not None and not isinstance(values['ids'], str):
                raise DomainError('IDENTITY_PROVIDER_SCHEMA', 'SIMBAD别名字段不是来源声明的字符串列表')
            astrometric = {'schema_version': 'SimbadAstrometricEvidence/1',
                'evidence_id': 'astrometry-' + digest({'artifact': artifact['sha256'], 'oid': str(values['oid'])}),
                'target_id': target_id, 'identity_evidence_id': evidence_id, 'adapter_version': adapter_version,
                'source_artifact_ref': {'id': artifact['artifact_id'], 'version': 1, 'content_sha256': artifact['sha256']},
                'raw_values': {name: values.get(name) for name in ['ra', 'dec', *astrometry_fields]},
                'source_field_metadata': [column for column in response['metadata']
                    if str(column.get('name', '')).lower() in {'ra', 'dec', *astrometry_fields}],
                'fields_not_returned': [name for name in astrometry_fields if name not in values],
                'reference_epoch': None, 'pm_ra_convention': 'not_established_by_this_response',
                'coordinate_solution_role': 'not_established_by_this_response',
                'independent_parameter_epochs_or_correlations_known': False,
                'autonomous_match_granted': False, 'raw_uncertainties_preserved': True}
            if adapter_version == 'simbad-sesame-1':
                astrometric['adapter_native_values'] = next(n for n in response['native_records'] if n['oid'] == str(values['oid']))
                astrometric['native_auxiliary_fields_not_mapped_to_tap_ellipse'] = True
            astrometric_evidence.append(astrometric)
            valid_coordinates = (all(type(values[name]) in {int, float} and math.isfinite(values[name]) for name in ('ra', 'dec'))
                and 0 <= values['ra'] < 360 and -90 <= values['dec'] <= 90)
            target = {
                "schema_version": "VerifiedTarget/2",
                "target_id": target_id,
                "authority": "SIMBAD",
                "main_id": values["main_id"],
                "primary_otype": values["otype"],
                "aliases": list(
                    dict.fromkeys(
                        [
                            values["main_id"],
                            *[v.strip() for v in (values["ids"] or "").split("|") if v.strip()],
                        ]
                    )
                ),
                "coordinates": {
                    "ra_deg": values["ra"],
                    "dec_deg": values["dec"],
                    "frame": "ICRS",
                    "epoch": None,
                }
                if valid_coordinates
                else None,
                'coordinate_issues': [] if valid_coordinates else ['source_coordinate_missing_nonfinite_or_out_of_range'],
                'astrometry_evidence_ref': {'id': astrometric['evidence_id'], 'version': 1, 'content_sha256': content_hash(astrometric)},
                "submitted_mentions": [mention],
                "resolution_method": "exact_name",
                "evidence_id": evidence_id,
                "retrieved_at": metadata["retrieved_at"],
                "raw_type_fields": {"otype": values["otype"]},
                "classification_assertions": [
                    {
                        "assertion_id": new_id(),
                        "subject_identity_ref": target_id,
                        "raw_code": values["otype"],
                        "canonical_otype": values["otype"],
                        "state": "candidate" if "?" in values["otype"] else "current_verified",
                        "origin": "current_primary",
                        "verification_rule_id": "simbad-sesame-exact-1" if adapter_version == "simbad-sesame-1" else "simbad-current-exact-1",
                        "evidence_refs": [evidence_id],
                    }
                ],
                "classification_completeness": {
                    "primary": "verified",
                    "secondary": "not_returned",
                    "adapter_capabilities": ["current_primary", "exact_aliases"],
                        "adapter_version": adapter_version,
                },
            }
            secondary = values.get('otypes')
            if secondary is not None:
                if not isinstance(secondary, str):
                    raise DomainError('IDENTITY_PROVIDER_SCHEMA', 'SIMBAD次型字段不是原生字符串列表')
                target['raw_type_fields']['otypes'] = secondary
                for code in dict.fromkeys(c.strip() for c in secondary.split('|') if c.strip()):
                    if code == values['otype']:
                        continue
                    target['classification_assertions'].append({'assertion_id': new_id(),
                        'subject_identity_ref': target_id, 'raw_code': code, 'canonical_otype': code,
                        'state': 'candidate' if '?' in code else 'current_verified', 'origin': 'current_secondary',
                        'verification_rule_id': 'simbad-same-oid-alltypes-1', 'evidence_refs': [evidence_id]})
                target['classification_completeness'].update(secondary='returned_same_oid',
                    adapter_capabilities=['current_primary', 'exact_aliases', 'same_oid_secondary_types'])
            targets.append(target)
        return {
            "state": "matched" if targets else "not_found",
            "targets": targets,
            'astrometric_evidence': astrometric_evidence,
            "queried_names": [mention],
            "artifact": artifact,
            "metadata": metadata,
        }
