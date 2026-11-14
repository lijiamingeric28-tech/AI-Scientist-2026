"""Identifier syntax, namespace and navigation primitives; no semantic model consumer."""

from __future__ import annotations
import re
import unicodedata
from astroquery_ai.runtime.errors import DomainError
import re
import unicodedata


def identifier_typography(text):
    """Canonical minus typography inside B/J coordinate names only.

    Prefix, digits, precision and component suffix remain significant. Original
    source strings and numeric scientific values are never rewritten.
    """
    return re.sub(
        "(?<![A-Za-z0-9])([BJ]\\d{4})[−–‐‑─](\\d{2,4}(?:\\.\\d+)?[A-Za-z]?)(?![A-Za-z0-9])",
        "\\1-\\2",
        unicodedata.normalize("NFKC", text),
        flags=re.I,
    )


def exact_identifier(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainError("EMPTY_OBJECT_IDENTIFIER", "对象标识为空", 422)
    if re.fullmatch("[0-9.]+", value.strip()):
        raise DomainError("IDENTIFIER_NAMESPACE_MISSING", "裸编号没有来源命名空间", 422)
    folded = re.sub("\\s+", " ", identifier_typography(value).strip()).casefold()
    standard = re.fullmatch("(hd|hip|hr|ngc|ic|m|hcg)\\s*(\\d+[a-z]?)", folded)
    if standard:
        return standard[1] + ":" + standard[2]
    zone = re.fullmatch("(bd|cd|cpd)\\s*([+-]\\d{2})\\s*(\\d+[a-z]?)", folded)
    if zone:
        return zone[1] + ":" + zone[2] + ":" + zone[3]
    gaia = re.fullmatch("gaia\\s*dr([23])\\s+(\\d+)", folded)
    if gaia:
        return "gaia-dr" + gaia[1] + ":" + gaia[2]
    two_mass = re.fullmatch("2mass\\s*j?\\s*(\\d{8}[+-]\\d{7}[a-z]*)", folded)
    if two_mass:
        return "2mass:" + two_mass[1]
    return folded


def gaia_global_designation(column):
    return bool(
        column.get("datatype") in {"char", "unicodeChar"}
        and "meta.id" in (column.get("ucd") or "").split(";")
        and re.search(
            "unique source designation.*unique across all data releases",
            column.get("description") or "",
            re.I,
        )
    )


def declared_namespace(column: dict, namespace: str | None, *, table_metadata=None) -> str | None:
    if namespace is not None and (
        not isinstance(namespace, str) or not namespace.strip() or len(namespace) > 80
    ):
        raise DomainError("INVALID_ID_NAMESPACE", "对象编号命名空间无效", 422)
    metadata = " ".join((str(column.get(key) or "") for key in ("name", "id", "description")))
    description = column.get("description") or ""
    if namespace is None and 'meta.id' in str(column.get('ucd') or '').split(';'):
        label = str(column.get('name') or '').upper()
        unannotated = re.sub(r'\([^)]*\)', ' ', description)
        declared_words = {'SN':'Supernova','HD':'Henry Draper','HIP':'Hipparcos'}
        # Literal established catalogue prefixes in actual identifier metadata.
        # Generic Name/Source/ID columns never acquire an invented namespace.
        native_prefixes=[label,*([declared_words[label]] if label in declared_words else [])]
        if label in {'HD','HIP','HR','SAO','TYC','NGC','IC','M','SN'} and any(re.search(
                r'\b'+re.escape(word)+r'\s+(?:number|name|identifier|designation)\b', unannotated, re.I)
                for word in native_prefixes):
            return label
    pulsar_coordinate_name = (
        column.get("datatype") in {None, "char", "unicodeChar"}
        and re.search("\\bpulsar\\s+(?:name|identifier|designation)\\b", description, re.I)
        and (
            str(column.get("name", "")).casefold() in {"psrj", "psrb"}
            or (
                re.search("\\bB\\s*name\\b", description, re.I)
                and re.search("\\bJ\\s*name\\b", description, re.I)
            )
        )
    )
    if pulsar_coordinate_name and (namespace is None or namespace.strip().casefold() == "psr"):
        return "PSR"
    if (
        namespace is None
        and str(column.get("name", "")).casefold() == "2mass"
        and (column.get("datatype") in {None, "char", "unicodeChar"})
        and re.search("\\bdesignation\\b|\\bidentifier\\b|\\bsource name\\b", description, re.I)
    ):
        return "2MASS"
    if namespace is None and (
        {"meta.id", "meta.main"} <= set(str(column.get("ucd") or "").split(";"))
        or gaia_global_designation(column)
    ):
        context = table_metadata or {}
        native_context = description + ' ' + " ".join(
            (str(context.get(key) or "") for key in ("table_id", "description"))
        )
        releases = {
            m.upper() for m in re.findall("\\bGaia\\s*((?:E?DR)\\d+)\\b", native_context, re.I)
        }
        if len(releases) == 1:
            return declared_namespace(
                column, "Gaia " + next(iter(releases)), table_metadata=table_metadata
            )
    if namespace is None:
        return None
    pattern = (
        "(?<![A-Za-z0-9])"
        + "\\s*".join((re.escape(part) for part in namespace.strip().split()))
        + "(?![A-Za-z0-9])"
    )
    if not re.search(pattern, metadata, re.I):
        context = table_metadata or {}
        table_text = " ".join(
            (
                str(context.get(key) or "")
                for key in ("table_id", "description", "resource_description")
            )
        )
        explicit_releases = re.findall("\\bGaia\\s*((?:E?DR)\\d+)\\b", metadata, re.I)
        requested = re.fullmatch("Gaia\\s*((?:E?DR)\\d+)", namespace.strip(), re.I)
        primary_table_release = re.search(
            "\\bGaia\\s*((?:E?DR)\\d+)\\b", str(context.get("description") or ""), re.I
        )
        native_id = {"meta.id", "meta.main"} <= set(
            str(column.get("ucd") or "").split(";")
        ) or gaia_global_designation(column)
        if (
            not requested
            or not native_id
            or (not re.search(pattern, table_text, re.I))
            or (
                primary_table_release
                and primary_table_release[1].casefold() != requested[1].casefold()
            )
            or (
                explicit_releases
                and any((v.casefold() != requested[1].casefold() for v in explicit_releases))
            )
        ):
            raise DomainError("ID_NAMESPACE_UNSUPPORTED", "列及具体表元数据未支持该编号命名空间")
    return namespace.strip()


def local_identifier(alias: str, namespace: str | None) -> str | None:
    if namespace is None:
        return alias
    if namespace.casefold() == "2mass":
        match = re.fullmatch("\\s*2MASS\\s*J?\\s*(\\d{8}[+-]\\d{7}[A-Za-z]*)\\s*", alias, re.I)
        return match[1] if match else None
    local = (
        "([BJ]\\d+[+-]\\d+(?:\\.\\d+)?[A-Za-z]*)"
        if namespace.casefold() == "psr"
        else "([+-]?\\d.*)"
    )
    match = re.fullmatch(
        "\\s*" + "\\s*".join((re.escape(part) for part in namespace.split())) + "\\s*" + local,
        alias,
        re.I,
    )
    return match[1] if match else None


def identifier_selectors(alias, namespace, column=None):
    local = local_identifier(alias, namespace)
    # Navigation variants remove only SIMBAD's leading object-type marker.
    # Returned cells still require exact or source-evidenced identity checks.
    unmarked = re.sub(r'^(?:V\*|\*\*?|NAME|Cl)\s+', '', alias.strip())
    variant = (unmarked if unmarked != alias.strip() and column
               and column.get('datatype') in {'char','unicodeChar'} else None)
    if local is None:
        return [variant] if variant else []
    if namespace is None and variant:
        return list(dict.fromkeys([variant,local]))
    if namespace and namespace.casefold() == "2mass":
        return [local, "J" + local, "2MASS J" + local]
    if (
        namespace
        and namespace.casefold().startswith("gaia ")
        and column
        and gaia_global_designation(column)
    ):
        return [namespace + " " + local]
    return list(dict.fromkeys([local, *([variant] if variant else [])]))


def exact_rows(
    rows: list[dict],
    id_columns: list[str],
    aliases: list[str],
    namespaces: dict[str, str] | None = None,
) -> list[int]:
    known = {exact_identifier(alias) for alias in aliases}
    accepted = []
    for index, row in enumerate(rows):
        values = []
        for column in id_columns:
            value = row.get(column)
            if isinstance(value, str):
                if (namespaces or {}).get(column) and local_identifier(
                    value, namespaces[column]
                ) is None:
                    value = namespaces[column] + " " + value.strip()
                try:
                    values.append(exact_identifier(value))
                except DomainError:
                    pass
        if known.intersection(values):
            accepted.append(index)
    return accepted


def navigation_patterns(aliases):
    """Literal numeric tokens from verified aliases, NOT an identity rule."""
    patterns = []
    for alias in aliases:
        # This is retrieval navigation only. Returned names still go through
        # exact or source-evidenced identity; no marker removal grants a match.
        unmarked=re.sub(r'^(?:V\*|\*\*?|NAME|Cl)\s+','',alias.strip())
        words=unmarked.split()
        if re.fullmatch(r'[A-Za-z][A-Za-z0-9 +.\-]*',unmarked) and (
                len(re.sub(r'[^A-Za-z]','',unmarked))>=3 or re.fullmatch(r'[A-Za-z]+\s*\d{1,2}[A-Za-z]?',unmarked)):
            pattern='*'+'*'.join(words)+'*'
            if pattern not in patterns:patterns.append(pattern)
        tokens = re.findall("[0-9]+", alias)
        if any((len(token) >= 3 for token in tokens)):
            pattern = "*" + "*".join(tokens) + "*"
            if pattern not in patterns:
                patterns.append(pattern)
    return patterns
