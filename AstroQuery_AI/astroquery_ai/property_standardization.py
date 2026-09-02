"""P1 性质标准化节点（系统中枢）

职责：
1. SIMBAD 解析天体（main_id / otype / otypes / coords）
2. 根据 otype 加载对应 RAG 性质库
3. LLM 从 RAG 库中选出用户要的性质 → PropertySpec
   （target_schema 由 quality_adapter 从 PropertySpec 统一生成，见 L-02）

PropertySpec 格式：
[
  {
    "property_id": "fe_h",
    "name_cn": "[Fe/H] 铁丰度",
    "unit": "dex",
    "category": "physical",
    "ucd": "phys.abund.Fe",
    "description": "..."
  },
  ...
]

这是全系统的字段名白名单和标准单位表，三条提取路径（数据库/VLM/补充材料）都必须归一到它。
"""

import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
from openai import OpenAI

from .config import get_settings
from .state import MainGraphState
# 注: 不直接 import subgraph1.config —— 它会反向 import astroquery_ai.config,
# 在本模块被 astroquery_ai 包初始化期间导入时触发循环依赖 (test_smoke_network 暴露)。
# subgraph1.config.llm 即 Settings 的 DashScope 三件套, 此处直接用 get_settings()。

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════

RAG_DIR = Path(__file__).parent.parent / "rag_properties"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ═══════════════════════════════════════════════════════════════
# OTYPE → 父类映射（基于 SIMBAD 分类 1/2/4/5 的层级关系）
# 子类 otype 命中时，同时加载父类 RAG 库做性质合并。
# ═══════════════════════════════════════════════════════════════
OTYPE_PARENT: Dict[str, str] = {
    # ── 分类 4：星系 ── G 为基类
    "AGN": "G", "SyG": "G", "Sy1": "G", "Sy2": "G",
    "rG": "G", "LIN": "G", "QSO": "G", "Bla": "G", "BLL": "G",
    "LSB": "G", "bCG": "G", "SBG": "G", "H2G": "G", "EmG": "G",
    "GiP": "G", "GiG": "G", "GiC": "G", "BiC": "G",

    # ── 分类 1：恒星 ── * 为基类
    "Ma*": "*", "bC*": "*", "sg*": "*", "s*r": "*", "s*y": "*", "s*b": "*",
    "WR*": "*", "N*": "*", "Psr": "*",
    "Y*O": "*", "Or*": "*", "TT*": "*", "Ae*": "*", "out": "*", "HH": "*",
    "MS*": "*", "Be*": "*", "BS*": "*", "SX*": "*", "gD*": "*", "dS*": "*",
    "Ev*": "*", "RG*": "*", "HS*": "*", "HB*": "*", "RR*": "*",
    "WV*": "*", "Ce*": "*", "cC*": "*", "C*": "*", "S*": "*",
    "LP*": "*", "AB*": "*", "Mi*": "*", "OH*": "*", "pA*": "*",
    "RV*": "*", "PN": "*", "WD*": "*",
    "Pe*": "*", "a2*": "*", "RC*": "*",
    "**": "*", "EB*": "*", "El*": "*", "SB*": "*", "RS*": "*",
    "BY*": "*", "Sy*": "*", "XB*": "*", "LXB": "*", "HXB": "*",
    "CV*": "*", "No*": "*",
    "SN*": "*", "LM*": "*", "BD*": "*",
    "V*": "*", "Ir*": "*", "Er*": "*", "Ro*": "*", "Pu*": "*",
    "Em*": "*", "PM*": "*", "HV*": "*",

    # ── 分类 2：恒星集合 ── Cl* 为基类
    "GlC": "Cl*", "OpC": "Cl*",
    "As*": "Cl*", "St*": "Cl*", "MGr": "Cl*",

    # ── 分类 5：星系集合 ── ClG 为基类
    "IG": "ClG", "PaG": "ClG", "GrG": "ClG", "CGG": "ClG",
    "PCG": "ClG", "SCG": "ClG", "vid": "ClG",
}

# ═══════════════════════════════════════════════════════════════
# SIMBAD 解析（TAP/ADQL → CSV）
# ═══════════════════════════════════════════════════════════════

_SIMBAD_TAP = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"

# 一条 ADQL 拿回全部字段——通过 ident 表按任意名称匹配（不限于 main_id），
# 再用 main_id 回查 basic/alltypes/ids，避免通俗名找不到（如 Vega→* alf Lyr）。
_TAP_QUERY = (
    "SELECT b.main_id, b.otype, b.ra, b.dec, b.sp_type, a.otypes, i.ids "
    "FROM basic b "
    "JOIN ident id ON b.oid = id.oidref "
    "JOIN alltypes a ON b.oid = a.oidref "
    "JOIN ids i ON b.oid = i.oidref "
    "WHERE id.id = '{}'"
)


def _query_simbad_fallback(target_name: str) -> Optional[Dict]:
    """
    TAP 服务不可用时的兜底：用 astroquery Simbad 查询。

    SIMBAD TAP 服务间歇性超时（外部问题），fallback 保证 P1 仍能拿到
    main_id / otype(紧凑码) / ids(别名)。

    Returns:
        {main_id, otype, ra, dec, ids, ALIASES} 或 None
    """
    try:
        from astroquery.simbad import Simbad
        s = Simbad()
        s.add_votable_fields('ids', 'otype')
        s.TIMEOUT = 30
        res = s.query_object(target_name)
        if res is None or len(res) == 0:
            return None
        row = res[0]

        def _get(col):
            return str(row[col]).strip() if col in row.colnames and row[col] is not None else ''

        result = {
            'main_id': _get('main_id'),
            'otype': _get('otype'),
            'ra': _get('RA'),
            'dec': _get('DEC'),
            'ids': _get('ids'),
        }
        result['ALIASES'] = [a.strip() for a in result['ids'].split('|') if a.strip()]
        logger.info(f"[SIMBAD] fallback(astroquery) 成功: main_id={result['main_id']}, otype={result['otype']}, "
                   f"aliases={len(result['ALIASES'])}")
        return result
    except Exception as e:
        logger.warning(f"[SIMBAD] fallback(astroquery) 失败: {e}")
        return None


def query_simbad(target_name: str) -> tuple[Optional[Dict], Optional[str]]:
    """
    查询 SIMBAD（TAP ADQL → CSV，TAP 失败时 astroquery 兜底）。

    TAP basic.otype 返回标准紧凑码（AGN, dS*, BLL, OpC, s*r, SB*），
    fallback 的 astroquery otype 同为紧凑码。

    Returns:
        (result_dict, error_msg)
        result_dict: {main_id, otype, ra, dec, sp_type, otypes, ids, ALIASES}
    """
    safe_name = target_name.replace("'", "''")
    adql = _TAP_QUERY.format(safe_name)

    # 重试 2 次（网络抖动容错，30s 超时）
    last_err = None
    for attempt in range(1, 3):
        try:
            logger.info(f"[SIMBAD] TAP: {target_name} (attempt {attempt}/2)")
            resp = requests.get(
                _SIMBAD_TAP,
                params={"REQUEST": "doQuery", "LANG": "ADQL", "QUERY": adql, "FORMAT": "csv"},
                headers=HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            break
        except Exception as e:
            last_err = e
            logger.warning(f"[SIMBAD] TAP 请求失败 (attempt {attempt}/2): {e}")
            if attempt < 2:
                time.sleep(3)
    else:
        logger.error(f"[SIMBAD] TAP 请求失败: {last_err}")
        # TAP 不可用 → astroquery 兜底
        fb = _query_simbad_fallback(target_name)
        if fb:
            return fb, None
        return None, f"SIMBAD TAP 请求失败: {last_err}"

    lines = resp.text.strip().split('\n')
    if len(lines) < 2:
        return None, f"未找到天体: {target_name}"

    import csv
    import io
    reader = csv.DictReader(io.StringIO(resp.text))
    rows = list(reader)
    if not rows:
        return None, f"未找到天体: {target_name}"

    row = rows[0]
    row['ALIASES'] = [a.strip() for a in row.get('ids', '').split('|') if a.strip()]

    logger.info(
        f"[SIMBAD] main_id={row.get('main_id', '?')}, "
        f"otype={row.get('otype', '?')}, "
        f"aliases={len(row['ALIASES'])}"
    )
    return row, None

# ═══════════════════════════════════════════════════════════════
# RAG 加载
# ═══════════════════════════════════════════════════════════════

def _load_rag_file(code: str) -> Optional[Dict]:
    """加载单个 RAG JSON（按 SIMBAD compact code）。文件名转义：* → _star, / → _, 空格 → _"""
    fname = code.strip().replace('*', '_star').replace('/', '_').replace(' ', '_') + '.json'
    fp = RAG_DIR / fname
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text(encoding='utf-8'))
    except Exception as e:
        logger.warning(f"[RAG] 加载失败: {fp.name}, {e}")
        return None


def _resolve_parent(otype: str) -> Optional[str]:
    """为给定 OTYPE（紧凑码）查找父类码。未在映射表中则为顶层类型。"""
    return OTYPE_PARENT.get(otype.strip())


def _norm_name(cn: str) -> str:
    """性质中文名归一化（去空白），用作跨库同义去重键。"""
    return re.sub(r"[\s　]+", "", (cn or "").lower())


def _merge_properties(base_props: List[Dict], delta_props: List[Dict]) -> List[Dict]:
    """合并父类+子类性质，两层去重，子类覆盖父类：

    1. property_id 相同 → 覆盖（原逻辑）
    2. name_cn 归一化后相同 → 覆盖（跨库同义：父类 cluster_metallicity vs
       子类 metallicity 这类"仅差前缀/空格"的伪重复，合并后只留子类一条）
    """
    merged: Dict[str, Dict] = {}
    by_name: Dict[str, str] = {}
    for p in base_props:
        merged[p["property_id"]] = p
        key = _norm_name(p.get("name_cn", ""))
        if key:
            by_name[key] = p["property_id"]
    for p in delta_props:
        pid = p["property_id"]
        key = _norm_name(p.get("name_cn", ""))
        if key and key in by_name and by_name[key] != pid:
            logger.info(
                f"[RAG] 跨库同义合并: {by_name[key]} → {pid}（name_cn 归一化一致）"
            )
            merged.pop(by_name[key], None)
        merged[pid] = p  # 子类覆盖
        if key:
            by_name[key] = pid
    return list(merged.values())


def load_rag_properties(simbad_result: Dict) -> Optional[Dict]:
    """
    根据 SIMBAD 官方 otype 加载 RAG 性质库。

    逻辑：
    1. OTYPE 查 OTYPE_PARENT → 有父类？双库拼合（父类基库 + 子类特库）
    2. OTYPE 无父类？直接加载 otype 对应的 JSON
    3. 都失败 → OTYPES 逐个回退 → _star.json 兜底

    Returns:
        {
          "otype": "AGN",
          "name_cn": "活动星系核 (含星系通用性质)",
          "properties": [{property_id, name_cn, unit, category, ucd, ...}, ...]
        }
    """
    if not simbad_result:
        return None

    otype = simbad_result.get('otype', '')
    if not otype:
        otype = ''

    # ── 双库拼合（核心）──
    otypes_raw = simbad_result.get('otypes', '')
    parent_code = _resolve_parent(otype)
    if parent_code:
        parent_rag = _load_rag_file(parent_code)
        subtype_rag = _load_rag_file(otype.strip())

        if parent_rag and subtype_rag:
            merged_props = _merge_properties(
                parent_rag.get('properties', []),
                subtype_rag.get('properties', []),
            )
            result = {
                "otype": otype,
                "name_cn": f"{subtype_rag.get('name_cn', '?')} (含{parent_rag.get('name_cn', '?')})",
                "description": subtype_rag.get('description', ''),
                "properties": merged_props,
            }
            logger.info(
                f"[RAG] 双库拼合: {parent_code}({len(parent_rag.get('properties',[]))}条) "
                f"+ {subtype_rag.get('otype', otype)}({len(subtype_rag.get('properties',[]))}条) "
                f"→ 去重后 {len(merged_props)} 条"
            )
            return result

        if subtype_rag:
            logger.info(f"[RAG] 父类 {parent_code} 缺库，仅加载子类: {otype}")
            return subtype_rag

    # ── 单库：otype 直接加载 ──
    rag = _load_rag_file(otype.strip())
    if rag:
        logger.info(f"[RAG] 加载成功 (OTYPE): {otype} ({rag.get('name_cn', '?')}), "
                   f"{len(rag.get('properties', []))} 条")
        return rag

    # ── 回退：OTYPES 逐个尝试 ──
    otypes = simbad_result.get('otypes', '')
    if otypes:
        for code in otypes.split('|'):
            code = code.strip()
            if not code:
                continue
            rag = _load_rag_file(code)
            if rag:
                logger.info(f"[RAG] 加载成功（回退 OTYPES）: {code} ({rag.get('name_cn', '?')})")
                return rag

    # ── 兜底：通用恒星 ──
    rag = _load_rag_file('*')
    if rag:
        logger.info("[RAG] 加载成功（兜底）: _star.json")
        return rag

    logger.error("[RAG] 未找到任何可用的性质库")
    return None

# ═══════════════════════════════════════════════════════════════
# LLM 筛选
# ═══════════════════════════════════════════════════════════════

def build_selection_prompt(rag: Dict, target_name: str, user_request: str) -> str:
    """构造 LLM 选性质的 prompt"""
    props = rag.get('properties', [])
    by_cat = defaultdict(list)
    for p in props:
        by_cat[p.get('category', 'other')].append(p)

    cat_names = {
        'photometry': '[测光]',
        'spectroscopy': '[光谱]',
        'physical': '[物理]',
        'astrometry': '[天体测量]',
        'variability': '[变化性]',
        'classification': '[分类]',
        'environment': '[环境]',
        'identification': '[标识]'
    }

    parts = []
    for cat, plist in by_cat.items():
        parts.append(f"\n## {cat_names.get(cat, cat)}")
        for p in plist:
            pid = p['property_id']
            cn = p.get('name_cn', '')
            unit = p.get('unit', '')
            desc = (p.get('description', '') or '')[:100]
            parts.append(f"  [{pid}] {cn} (单位: {unit or '无'}) - {desc}")

    return f"""你是天体物理数据查询助手。任务：根据用户需求，从给定性质库中选出相关性质。

## 查询天体
名称: {target_name}
类型: {rag['otype']} ({rag.get('name_cn', '')})
描述: {rag.get('description', '')}

## 用户需求
{user_request}

## 可用性质库
每行格式：[property_id] 中文名 (单位) - 描述
{chr(10).join(parts)}

## 选择步骤（按思维链顺序执行：读查询 → 读备选 → 定颗粒度 → 挑性质）

**Step 1 读查询性质**：解析用户需求，确定物理概念列表（如"红移""距离""金属丰度"）。

**Step 2 读备选性质**：对每个概念，读库中所有候选性质的 description，
观察候选之间的区分维度（物理表征 / 观测方法 / 波段仪器 / 不可区分）。

**Step 3 确定颗粒度**：为该概念选择有意义的细化维度——
   - 候选按物理表征或观测方法区分且互不等价 → 按该维度细化
   - 候选只是同一物理量的波段/名称变体 → 合并为一个代表
   - 库中仅 1 个候选 → 不细化
   每个概念的细化维度可不同，由候选实际结构决定。

**Step 4 挑选实际查询性质**：按 Step 3 确定的颗粒度，从备选中选出最终集合。
每个入选候选必须同时满足：
   ① 直接回答用户概念（description 为依据）
   ② 与同概念其他入选者同级（无具体化/被具体化关系）
   ③ 与同概念其他入选者物理异构（度量方式或量纲不同）
   ④ 不与任何已选性质同义（中文名/单位/ucd 主成分相同即视为同义）

## 同义性质识别（重要）
- 库中可能存在多个 property_id 描述同一物理量：如某量同时出现带
  "cluster_" 前缀与不带前缀的两个条目，或名称仅差一个"视"字
  （"距离模数" vs "视距离模数"），中文名、单位、含义实质相同。
- 识别方法：中文名相同或仅差冗余前缀/修饰词 + 单位相同 +
  description 指向同一物理量。
- 处理：视为同一性质，只选其中一个，禁止同时选中同义性质。
- 选择优先级：① 描述更精确完整（如"积分V星等 Vt"优于"积分星等与绝对星等"）
  → ② 名称不带冗余前缀/更贴近用户措辞的 → ③ 单位更标准化的。
- 若两候选物理量相同但颗粒度不同（一个合并、一个拆分为多个），
  按 Step 3 颗粒度规则选择，并在 reason 中写明为何选该颗粒度。

## 其他规则
- 只能从上述性质库中选择，不得臆造 property_id
- 用户关注精度时（如"误差""不确定度"），可额外包含对应不确定度性质
- 模糊请求（"基本参数"、"全部"）或空请求（未指定、直接回车、说"都行"）
  → 选 10-15 个最基础的性质

## 距离的成对性质（重要，勿漏选）
- 当用户请求"距离"这一概念时，若库中**同时存在** `distance`（实际距离，长度单位 pc/kpc/Mpc）
  与 `dist_modulus`（距离模数 (m-M)，单位 mag）两个性质，应**同时选中两者**。
  原因：论文中"距离"和"距离模数"都会出现，两者是同一物理概念的不同表示；
  若只选 distance，VLM 提取时会把带 mag 的距离模数硬塞进 distance，造成单位污染。
- 若库中只有其一，则只选存在的那个。

## 输出（严格 JSON，不要任何解释文字）
每个条目必须携带 group 字段（= 该性质所属的物理概念，即 Step 1 解析出的概念名）：
{{
  "requested_properties": [
    {{"property_id": "parallax", "group": "距离", "reason": "直接回答距离概念，与同概念其他入选者同级异构"}},
    {{"property_id": "distance_sun", "group": "距离", "reason": "直接回答距离概念，度量方式与视差不同"}},
    {{"property_id": "cluster_age", "group": "年龄", "reason": "直接回答年龄概念"}}
  ]
}}"""

def select_properties_with_llm(
    rag: Dict,
    target_name: str,
    user_request: str
) -> tuple[Optional[List[Dict]], Optional[str]]:
    """
    用 LLM 从 RAG 性质库中筛选用户要的性质

    Returns:
        (selected_properties, error_msg)
        selected_properties: [{"property_id": "...", "reason": "..."}, ...]
    """
    prompt = build_selection_prompt(rag, target_name, user_request)

    try:
        _s = get_settings()
        client = OpenAI(
            base_url=_s.dashscope_base_url,
            api_key=_s.dashscope_api_key
        )

        model = get_settings().p1_model
        logger.info(f"[LLM] 调用模型筛选性质: {model}")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是天体物理数据查询助手，严格按 JSON 格式输出。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=4096
        )

        response_text = response.choices[0].message.content
        logger.debug(f"[LLM] 原始响应: {response_text[:200]}...")

        # 容忍 markdown 围栏
        text = response_text.strip()
        text = re.sub(r'^```\w*\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        # 提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = json.loads(text)

        selected = result.get('requested_properties', [])

        # H-05 fix: LLM 输出形状校验 —— 过滤非 dict / 缺 property_id 的条目，
        # 避免 [item['property_id'] for item in selected] 直接 TypeError 使整阶段静默失败
        valid_items = []
        invalid_count = 0
        for item in selected:
            if isinstance(item, dict) and item.get('property_id'):
                valid_items.append(item)
            else:
                invalid_count += 1
        if invalid_count:
            logger.warning(
                f"[LLM] 过滤 {invalid_count} 个非法 requested_properties 条目"
                f"（非 dict 或缺 property_id）"
            )
        if not valid_items:
            err = "LLM 返回的 requested_properties 全部非法（非 dict 或缺 property_id）"
            logger.error(f"[LLM] {err}")
            return None, err

        selected = valid_items
        logger.info(f"[LLM] 筛选出 {len(selected)} 个性质")
        return selected, None

    except Exception as e:
        err = f"LLM 筛选失败: {e}"
        logger.error(f"[LLM] {err}")
        return None, err

# ═══════════════════════════════════════════════════════════════
# PropertySpec 构建
# ═══════════════════════════════════════════════════════════════

def build_property_spec(
    rag: Dict,
    selected: List[Dict],
) -> List[Dict]:
    """
    从 RAG 完整信息构造 PropertySpec

    Args:
        rag: RAG 性质库
        selected: LLM 筛选结果 items（含 property_id / group / reason）

    Returns:
        PropertySpec: [{property_id, name_cn, unit, category, ucd, description, group}, ...]
        group 为概念族名（P1 解析，ADS 查询按组消费，不再二次分组）
    """
    props = rag.get('properties', [])
    prop_map = {p['property_id']: p for p in props}

    spec = []
    for item in selected:
        pid = item.get('property_id', '')
        if pid in prop_map:
            p = prop_map[pid]
            spec.append({
                'property_id': p['property_id'],
                'name_cn': p.get('name_cn', ''),
                'unit': p.get('unit', ''),
                'category': p.get('category', ''),
                'ucd': p.get('ucd', ''),
                'description': p.get('description', ''),
                # 概念族名（2026-08-11）：LLM 输出缺失时用性质名兜底，
                # ADS 侧按此分组构造查询串
                'group': item.get('group') or p.get('name_cn', '') or p['property_id'],
            })
        else:
            logger.warning(f"[PropertySpec] 性质 {pid} 在 RAG 库中不存在，跳过")

    logger.info(f"[PropertySpec] 构建完成: {len(spec)} 个性质")
    return spec

# ═══════════════════════════════════════════════════════════════
# P1 主节点
# ═══════════════════════════════════════════════════════════════

def property_standardization_node(state: MainGraphState) -> MainGraphState:
    """
    P1 性质标准化节点

    输入：
      - target_entity: Node1 澄清的天体名
      - requested_properties: Node1 提取的性质原文（可能是中文/口语）

    输出：
      - simbad_info: {main_id, otype(紧凑码), otypes, sp_type, ra, dec, ...}
      - property_spec: PropertySpec（字段名白名单 + 标准单位表）
      - error_log: 若有错误
      注：target_schema 由 quality_adapter 从 property_spec 统一生成（L-02）
    """
    logger.info("=" * 60)
    logger.info("[P1] 性质标准化节点启动")
    logger.info("=" * 60)

    target_entity = state.get('target_entity')
    if not target_entity:
        err = "缺少 target_entity，无法进行性质标准化"
        logger.error(f"[P1] {err}")
        return {
            "error_log": [{
                "node": "P1_property_standardization",
                "error": err,
                "timestamp": datetime.now().isoformat()
            }]
        }

    # Web 埋点：卡 1 子步骤（契约 D6-4）—— 进入 P1 即澄清完成
    qid = state.get("query_id", "")
    try:
        from events import emit_progress
        emit_progress(qid, "understand", "confirm", "completed")
        emit_progress(qid, "understand", "simbad", "running")
    except Exception:
        pass

    # Step 1: SIMBAD 解析
    simbad_result, err = query_simbad(target_entity)

    try:
        from events import emit_progress
        emit_progress(qid, "understand", "simbad", "completed")
    except Exception:
        pass
    if err or not simbad_result:
        error_msg = err or "SIMBAD 查询返回空"
        logger.error(f"[P1] SIMBAD 查询失败: {error_msg}")
        return {
            "error_log": [{
                "node": "P1_property_standardization",
                "error": error_msg,
                "timestamp": datetime.now().isoformat()
            }]
        }

    try:
        from events import emit_progress
        emit_progress(qid, "understand", "research", "running")
    except Exception:
        pass

    # Step 2: 加载 RAG 性质库
    rag = load_rag_properties(simbad_result)
    if not rag:
        err = f"未找到 otype={simbad_result.get('otype', '?')} 的 RAG 性质库"
        logger.error(f"[P1] {err}")
        return {
            "simbad_info": simbad_result,
            "error_log": [{
                "node": "P1_property_standardization",
                "error": err,
                "timestamp": datetime.now().isoformat()
            }]
        }

    # Step 3: LLM 筛选性质
    # 用户原始请求：如果 Node1 提取了 requested_properties，用它；否则用 user_query
    user_request = state.get('user_query', '')
    if state.get('requested_properties'):
        # Node1 已提取性质，但可能是英文标准名（旧逻辑）或中文口语（新逻辑）
        # 无论哪种，都把它拼成自然语言给 LLM 重新理解
        props_str = ', '.join(state['requested_properties'])
        user_request = f"{target_entity} 的 {props_str}"

    selected, err = select_properties_with_llm(rag, target_entity, user_request)
    if err or not selected:
        error_msg = err or "LLM 未返回任何性质"
        logger.error(f"[P1] LLM 筛选失败: {error_msg}")
        return {
            "simbad_info": simbad_result,
            "error_log": [{
                "node": "P1_property_standardization",
                "error": error_msg,
                "timestamp": datetime.now().isoformat()
            }]
        }

    # Step 4: 构建 PropertySpec
    # 2026-08-11: 传入完整 items（含 group 概念族名，ADS 查询按组消费，不再二次分组）
    property_spec = build_property_spec(rag, selected)

    if not property_spec:
        err = "PropertySpec 为空"
        logger.error(f"[P1] {err}")
        return {
            "simbad_info": simbad_result,
            "error_log": [{
                "node": "P1_property_standardization",
                "error": err,
                "timestamp": datetime.now().isoformat()
            }]
        }

    # Step 5: target_schema 由 quality_adapter 从 property_spec 统一生成
    # （L-02 fix: 消除双实现漂移 —— P1 不再生成/写入 state.target_schema）

    # Web 埋点：卡 1 子步骤 research 完成（契约 D6-4）
    try:
        from events import emit_progress
        emit_progress(qid, "understand", "research", "completed")
    except Exception:
        pass

    logger.info(f"[P1] 完成: SIMBAD={simbad_result.get('main_id', '?')}, "
               f"otype={simbad_result.get('otype', '?')}, "
               f"PropertySpec={len(property_spec)} 个性质")

    return {
        "simbad_info": simbad_result,
        "property_spec": property_spec,
    }
