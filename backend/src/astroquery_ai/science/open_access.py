"""DOI-bound Unpaywall locations; metadata is a hint, not manuscript proof."""

from urllib.parse import urlsplit

from astroquery_ai.runtime.errors import DomainError
from .literature import normalize_doi


def doi_locations(document, expected_doi, *, include_landing=False):
    if not isinstance(document, dict):
        raise DomainError("OA_METADATA_SCHEMA", "开放版本元数据不是对象", 422)
    try:
        same_doi = normalize_doi(document.get("doi", "")) == normalize_doi(expected_doi)
    except (ValueError, TypeError, AttributeError):
        same_doi = False
    if not same_doi:
        raise DomainError("OA_METADATA_IDENTITY", "开放版本元数据未绑定目标DOI", 422)
    locations = document.get("oa_locations", [])
    if not isinstance(locations, list):
        raise DomainError("OA_METADATA_SCHEMA", "开放版本位置列表无效", 422)
    best = document.get("best_oa_location")
    if isinstance(best, dict):
        locations = [best, *locations]
    ranks = {"publishedVersion": 0, "acceptedVersion": 1, "submittedVersion": 2}
    result, seen = [], set()
    for location in locations:
        if not isinstance(location, dict):
            continue
        url = location.get("url_for_pdf") or (location.get('url_for_landing_page') if include_landing else None)
        if not isinstance(url, str) or url in seen:
            continue
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            continue
        seen.add(url)
        result.append(
            {
                "url": url,
                "rank_hint": ranks.get(location.get("version"), 3),
                "version_hint": location.get("version"),
                "host_type": location.get("host_type"),
                "license": location.get("license"),
                "landing_url": location.get("url_for_landing_page"),
                "doi": normalize_doi(expected_doi),
                "manuscript_identity_verified": False,
                "actual_version_grade_verified": False,
            }
        )
    return sorted(result, key=lambda item: (item["rank_hint"], item["url"]))[:8]
