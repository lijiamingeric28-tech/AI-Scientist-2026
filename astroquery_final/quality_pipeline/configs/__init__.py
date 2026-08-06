"""configs/ — 配置文件解析 (V3.0: 领域感知)"""
import os, yaml, threading

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


def load_domain_config(section: str, default_section: str = "") -> dict:
    """
    领域感知的配置加载。

    根据当前 research_domain 选择领域专属配置段:
      - 先尝试 "{section}_{domain}" (如 'semantic_types_astrophysics')
      - 再尝试 "{section}" (通用配置)
      - 最后尝试 default_section

    Args:
        section: 配置段名 (如 'semantic_types', 'journal_tiers')
        default_section: 如果领域专属段不存在, 使用的备选段名
    """
    domain = get_research_domain()
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


def load_domain_schema_config(section: str) -> dict:
    """
    领域感知的 schema_mapping 配置加载。
    同 load_domain_config, 但读取 schema_mapping.yaml。
    """
    domain = get_research_domain()
    config = load_yaml("schema_mapping.yaml")

    if domain:
        domain_key = f"{section}_{domain}"
        domain_val = config.get(domain_key)
        if domain_val:
            return domain_val

    return config.get(section, {})
