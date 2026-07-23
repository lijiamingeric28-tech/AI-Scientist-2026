"""
检索子图的Prompt模板

包含查询扩展、Topic检测等LLM调用的Prompt模板
"""

# ==========================================
# Agent A: 查询扩展 - 同义词扩展
# ==========================================

def SYNONYM_EXPANSION_PROMPT(entities: list, properties: list, domain: str = "astronomy") -> str:
    """
    同义词扩展Prompt模板

    用于将用户输入的实体和属性扩展为同义词，并自动翻译中文到英文

    Args:
        entities: 实体列表
        properties: 属性列表
        domain: 领域（默认astronomy）

    Returns:
        格式化的Prompt字符串
    """
    return f"""你是{domain}领域的专家。请为以下实体和属性生成同义词扩展，包括：
1. 英文同义词、缩写、全称
2. 如果输入是中文，必须翻译为对应的英文术语
3. 相关的技术术语和变体

输入：
实体（entities）: {entities}
属性（properties）: {properties}

要求：
- 保留原始词汇
- 添加同义词、缩写、全称
- **中文词汇必须翻译为英文**（OpenAlex只支持英文）
- 单复数变体
- 专业术语的标准写法
- **每个实体最多扩展为5个变体，每个属性最多扩展为5个变体**（避免查询过长）

示例1（天文学）：
输入：entities=["快速射电暴"], properties=["色散量"]
输出：
{{
    "expanded_entities": ["FRB", "fast radio burst", "fast radio bursts", "fast radio transient"],
    "expanded_properties": ["dispersion measure", "DM", "dispersion"]
}}

示例2（天文学）：
输入：entities=["FRB"], properties=["red shift"]
输出：
{{
    "expanded_entities": ["FRB", "fast radio burst", "fast radio bursts"],
    "expanded_properties": ["redshift", "z", "cosmological redshift"]
}}

请严格按照JSON格式输出，不要添加其他文字：
"""


# ==========================================
# Agent A: 查询扩展 - Topic检测
# ==========================================

def TOPIC_DETECTION_PROMPT(user_query: str, entities: list, properties: list, topics_text: str) -> str:
    """
    Topic检测Prompt模板

    使用LLM检测用户查询对应的OpenAlex Topics（最多3个）

    Args:
        user_query: 用户原始查询
        entities: 实体列表
        properties: 属性列表
        topics_text: 格式化的Topics列表文本

    Returns:
        格式化的Prompt字符串
    """
    entities_str = ", ".join(entities) if entities else "无"
    properties_str = ", ".join(properties) if properties else "无"

    return f"""你是天文学领域专家。请根据用户查询，判断最相关的OpenAlex Topic（最多3个）。

用户查询: {user_query}
提取的实体: {entities_str}
提取的属性: {properties_str}

可选Topics（按相关性排序）:
{topics_text}

要求:
1. 选择最相关的1-3个Topic ID
2. 如果查询明确提到FRB、快速射电暴、射电天文，优先选择T12450
3. 如果涉及爆发、瞬变现象，考虑T11323
4. 如果查询涉及脉冲星、引力波，考虑T10463
5. 如果无法确定具体Topic，返回"UNKNOWN"（将使用Subfield 3103）
6. 只返回Topic ID，用逗号分隔，不要其他文字

输出格式示例:
T12450,T11323
或
UNKNOWN
"""


# ==========================================
# 天文学Topics映射表
# ==========================================

ASTRONOMY_TOPICS = {
    "T12450": {
        "name": "Radio Astronomy Observations and Technology",
        "keywords": ["radio astronomy", "FRB", "fast radio burst", "radio telescope", "SKA", "21 cm", "pulsar", "radio transient", "射电天文", "快速射电暴"],
        "description": "射电天文观测技术，FRB、脉冲星等"
    },
    "T11323": {
        "name": "Gamma-ray bursts and supernovae",
        "keywords": ["gamma-ray burst", "GRB", "supernova", "transient", "kilonova", "explosion", "伽马射线暴", "超新星"],
        "description": "伽马射线暴、超新星爆发"
    },
    "T10744": {
        "name": "Astrophysical Phenomena and Observations",
        "keywords": ["black hole", "accretion", "X-ray", "AGN", "quasar", "astrophysical", "黑洞", "吸积"],
        "description": "天体物理现象（黑洞、吸积盘等）"
    },
    "T10463": {
        "name": "Pulsars and Gravitational Waves Research",
        "keywords": ["pulsar", "gravitational wave", "neutron star", "binary", "LIGO", "脉冲星", "引力波"],
        "description": "脉冲星和引力波研究"
    },
    "T10477": {
        "name": "Astrophysics and Star Formation Studies",
        "keywords": ["star formation", "stellar", "molecular cloud", "恒星形成"],
        "description": "恒星形成与演化"
    },
    "T11803": {
        "name": "Superconducting and THz Device Technology",
        "keywords": ["superconducting", "THz", "detector", "超导", "太赫兹"],
        "description": "超导和太赫兹探测技术"
    },
    "T10026": {
        "name": "Galaxies: Formation, Evolution, Phenomena",
        "keywords": ["galaxy", "galactic", "spiral", "elliptical", "星系"],
        "description": "星系形成与演化"
    },
    "T10039": {
        "name": "Stellar, planetary, and galactic studies",
        "keywords": ["stellar", "planetary", "exoplanet", "行星", "系外行星"],
        "description": "恒星、行星和星系研究"
    },
    "T10095": {
        "name": "Cosmology and Gravitation Theories",
        "keywords": ["cosmology", "dark matter", "dark energy", "宇宙学", "暗物质"],
        "description": "宇宙学和引力理论"
    },
    "T10159": {
        "name": "Ionosphere and magnetosphere dynamics",
        "keywords": ["ionosphere", "magnetosphere", "plasma", "电离层", "磁层"],
        "description": "电离层和磁层动力学"
    },
    "T10251": {
        "name": "Solar and Space Plasma Dynamics",
        "keywords": ["solar", "space weather", "CME", "太阳", "空间天气"],
        "description": "太阳和空间等离子体动力学"
    },
    "T10325": {
        "name": "Astro and Planetary Science",
        "keywords": ["asteroid", "comet", "meteorite", "小行星", "彗星"],
        "description": "天文和行星科学"
    },
    "T10406": {
        "name": "Planetary Science and Exploration",
        "keywords": ["Mars", "Venus", "Jupiter", "planetary exploration", "行星探测"],
        "description": "行星科学与探测"
    },
    "T10787": {
        "name": "Lightning and Electromagnetic Phenomena",
        "keywords": ["lightning", "electromagnetic", "闪电", "电磁"],
        "description": "闪电和电磁现象"
    },
    "T11445": {
        "name": "Origins and Evolution of Life",
        "keywords": ["astrobiology", "origin of life", "天体生物学", "生命起源"],
        "description": "生命起源与演化"
    },
    "T11960": {
        "name": "Relativity and Gravitational Theory",
        "keywords": ["general relativity", "gravitational", "spacetime", "广义相对论", "时空"],
        "description": "相对论和引力理论"
    },
    "T12717": {
        "name": "Space exploration and regulation",
        "keywords": ["space exploration", "satellite", "space law", "空间探索", "卫星"],
        "description": "空间探索与监管"
    },
    "T12788": {
        "name": "Space Science and Extraterrestrial Life",
        "keywords": ["space science", "extraterrestrial", "SETI", "空间科学", "外星生命"],
        "description": "空间科学与地外生命"
    },
    "T12836": {
        "name": "History and Developments in Astronomy",
        "keywords": ["history of astronomy", "astronomical history", "天文史"],
        "description": "天文学历史与发展"
    },
    "T13080": {
        "name": "Advanced Differential Geometry Research",
        "keywords": ["differential geometry", "mathematical physics", "微分几何"],
        "description": "高等微分几何研究"
    },
    "T13175": {
        "name": "Historical Astronomy and Related Studies",
        "keywords": ["historical astronomy", "古天文", "天文史"],
        "description": "历史天文学及相关研究"
    }
}
