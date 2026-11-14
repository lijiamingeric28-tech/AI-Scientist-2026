"""User defaults and per-query overrides; running tasks use only their frozen policy."""
from .errors import DomainError

SORTS = {"score desc", "date desc", "citation_count desc", "read_count desc"}
DEFAULT_PAPERS = 20


def papers_value(value):
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if type(value) is not int or not 1 <= value <= 40:
        raise DomainError("LITERATURE_TARGET_INVALID", "每项性质的论文目标须为 1–40 的整数", 422)
    return value


def resolve_preferences(configuration, overrides=None):
    if overrides is not None and (not isinstance(overrides, dict) or set(overrides) - {"papers_per_property", "ads_sort"}):
        raise DomainError("RETRIEVAL_PREFERENCES_INVALID", "查询偏好格式无效", 422)
    values = overrides or {}
    runtime = configuration.runtime
    target = papers_value(values.get("papers_per_property", runtime.get("literature_papers_per_property", DEFAULT_PAPERS)))
    sort = values.get("ads_sort", runtime.get("ads_sort") or "score desc")
    if not isinstance(sort, str) or sort not in SORTS:
        raise DomainError("ADS_SORT_INVALID", "ADS 排序须为支持的四种顺序", 422)
    return {"papers_per_property": target, "ads_sort": sort}


def readable_target(spec):
    """Historical specs retain their own value, with the original default of twenty."""
    policy = spec.get("run_policy", {}).get("literature", {})
    value = policy.get("selected_limit", DEFAULT_PAPERS)
    if type(value) is not int or value < 1:
        raise DomainError("LITERATURE_TARGET_INVALID", "已冻结的论文目标无效", 422)
    return value
