"""configs/ — 配置文件解析 (V3.0: 领域感知)"""
import os
import yaml
import threading

_domain_cache: dict[int, str] = {}  # thread_id → domain
# V4 fix: 全局领域兜底 — ThreadPoolExecutor 工作线程无 domain 缓存 (线程本地),
# 并行执行 (如 Normalization 每 source 一线程) 时 get_research_domain() 返回 ""
# → 加载材料规则 → 天体物理单位转换全部失败 (53 次 UnitConv 全 0 converted)。
_global_domain: str = ""


def set_research_domain(domain: str):
    """设置当前线程的研究领域 (在 pipeline 入口调用)。"""
    _domain_cache[threading.get_ident()] = domain
    global _global_domain
    _global_domain = domain


def get_research_domain() -> str:
    """获取当前研究领域, 默认 materials_science。

    V4 fix: 线程本地查不到时回退全局值 (并行工作线程继承主线程领域)。
    """
    return _domain_cache.get(threading.get_ident(), _global_domain)


def load_yaml(filename: str) -> dict:
    config_dir = os.path.dirname(__file__)
    filepath = os.path.join(config_dir, filename)
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ── A11 fix: 质量评分运行参数 (单点定义 + fallback) ──
# 原 volume/agreement/repair_cost/extraction/conflict_severity/level 阈值
# 全部硬编码散落在 quality_scoring_agent / decision_reasoning_agent /
# quality_scoring 里, 改一处另一处失同步; 现统一从 yaml quality_scoring_runtime
# 段读取, 此默认值仅作 fallback (行为保持与旧硬编码一致)。
_QUALITY_SCORING_RUNTIME_DEFAULTS: dict = {
    "volume_thresholds": {10: 0.3, 100: 0.7, "else": 0.9},
    "agreement_std_coef": 2.0,
    "repair_cost": {"anomaly": [1, 3], "issues": [3, 10]},
    "extraction_human_threshold": 0.3,
    "conflict_severity": {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.2},
    "level_thresholds": {"excellent": 0.90, "good": 0.75, "fair": 0.60},
}


def load_quality_scoring_runtime() -> dict:
    """质量评分运行参数 (yaml quality_scoring_runtime 优先, fallback 内建默认)。

    dict 类型键按 key 级浅合并 (允许 yaml 只覆盖部分字段);
    非 dict 键 (标量) 直接取 yaml 值。yaml 缺失/损坏时回退默认, 行为不变。
    """
    cfg = load_yaml("quality_rules.yaml") or {}
    runtime = cfg.get("quality_scoring_runtime") or {}
    merged = dict(_QUALITY_SCORING_RUNTIME_DEFAULTS)
    for k, v in runtime.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    return merged


def load_domain_config(section: str, default_section: str = "",
                       research_domain: str | None = None) -> dict:
    """
    领域感知的配置加载。

    根据当前 research_domain 选择领域专属配置段:
      - 先尝试 "{section}_{domain}" (如 'semantic_types_astrophysics')
      - 再尝试 "{section}" (通用配置)
      - 最后尝试 default_section

    Phase 3 显式化: 优先用显式传入的 research_domain, None 时回退全局
    (get_research_domain), 兼容历史调用方与 LLM 工具路径。

    Args:
        section: 配置段名 (如 'semantic_types', 'journal_tiers')
        default_section: 如果领域专属段不存在, 使用的备选段名
        research_domain: 显式研究领域 (Phase 3 起调用方应传 state 值)
    """
    domain = research_domain or get_research_domain()
    config = load_yaml("quality_rules.yaml")

    # 1. 领域专属段
    if domain:
        domain_key = f"{section}_{domain}"
        domain_val = config.get(domain_key)
        if domain_val:
            return domain_val

    # 2. 通用段
    general_val = config.get(section)
    if general_val:
        return general_val

    # 3. 默认段
    if default_section:
        return config.get(default_section, {})

    return {}


def load_domain_schema_config(section: str, research_domain: str | None = None) -> dict:
    """
    领域感知的 schema_mapping 配置加载。
    同 load_domain_config, 但读取 schema_mapping.yaml。

    Phase 3 显式化: 优先显式 research_domain, None 时回退全局。
    """
    domain = research_domain or get_research_domain()
    config = load_yaml("schema_mapping.yaml")

    if domain:
        domain_key = f"{section}_{domain}"
        domain_val = config.get(domain_key)
        if domain_val:
            return domain_val

    return config.get(section, {})
