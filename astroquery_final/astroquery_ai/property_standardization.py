"""P1 性质标准化节点（系统中枢）

职责：
1. SIMBAD 解析天体（main_id / otype / otypes / coords）
2. 根据 otype 加载对应 RAG 性质库
3. LLM 从 RAG 库中选出用户要的性质 → PropertySpec
4. 生成 target_schema（供子图 4 消费）

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

from .state import MainGraphState
from .subgraph1.config import config as subgraph1_config

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

    import csv, io
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


def _merge_properties(base_props: List[Dict], delta_props: List[Dict]) -> List[Dict]:
    """合并父类+子类性质：按 property_id 去重，子类覆盖父类同名项"""
    merged: Dict[str, Dict] = {}
    for p in base_props:
        merged[p['property_id']] = p
    for p in delta_props:
        merged[p['property_id']] = p  # 子类覆盖
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

## 选择规则
1. **只能从上述性质库中选择**，不得臆造 property_id
2. **宽泛请求**（"radio properties"、"所有光度"）→ 包含该类别的所有相关性质
3. **模糊请求**（"基本参数"、"全部"）→ 选 10-15 个最基础的性质
4. **空请求**（用户未指定、直接回车、说"都行"）→ 选 10-15 个最基础的性质
5. **包含不确定度**（如 fe_h_err）当用户关注精度时
6. **输出必须严格 JSON，不要任何解释文字**

输出格式：
{{
  "requested_properties": [
    {{"property_id": "fe_h", "reason": "用户要求金属丰度"}},
    {{"property_id": "distance", "reason": "基本物理参数"}}
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
        client = OpenAI(
            base_url=subgraph1_config.llm['base_url'],
            api_key=subgraph1_config.llm['api_key']
        )

        model = "qwen3.8-max"
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
    selected_ids: List[str]
) -> List[Dict]:
    """
    从 RAG 完整信息构造 PropertySpec

    Args:
        rag: RAG 性质库
        selected_ids: LLM 筛选出的 property_id 列表

    Returns:
        PropertySpec: [{property_id, name_cn, unit, category, ucd, description}, ...]
    """
    props = rag.get('properties', [])
    prop_map = {p['property_id']: p for p in props}

    spec = []
    for pid in selected_ids:
        if pid in prop_map:
            p = prop_map[pid]
            spec.append({
                'property_id': p['property_id'],
                'name_cn': p.get('name_cn', ''),
                'unit': p.get('unit', ''),
                'category': p.get('category', ''),
                'ucd': p.get('ucd', ''),
                'description': p.get('description', '')
            })
        else:
            logger.warning(f"[PropertySpec] 性质 {pid} 在 RAG 库中不存在，跳过")

    logger.info(f"[PropertySpec] 构建完成: {len(spec)} 个性质")
    return spec

# ═══════════════════════════════════════════════════════════════
# target_schema 生成
# ═══════════════════════════════════════════════════════════════

def generate_target_schema(property_spec: List[Dict]) -> Dict:
    """
    从 PropertySpec 生成 target_schema（供子图 4 消费）

    Returns:
        {
          "fields": [
            {"name": "fe_h", "standard_unit": "dex", "semantic_type": "metallicity", ...},
            ...
          ]
        }
    """
    fields = []
    for p in property_spec:
        fields.append({
            'name': p['property_id'],
            'standard_unit': p['unit'],
            'semantic_type': p.get('category', ''),  # 暂用 category 作 semantic_type
            'ucd': p.get('ucd', ''),
            'description': p.get('description', '')
        })

    return {'fields': fields}

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
      - target_schema: 子图 4 消费的结构
      - error_log: 若有错误
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

    # Step 1: SIMBAD 解析
    simbad_result, err = query_simbad(target_entity)
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
    selected_ids = [item['property_id'] for item in selected]
    property_spec = build_property_spec(rag, selected_ids)

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

    # Step 5: 生成 target_schema
    target_schema = generate_target_schema(property_spec)

    logger.info(f"[P1] 完成: SIMBAD={simbad_result.get('main_id', '?')}, "
               f"otype={simbad_result.get('otype', '?')}, "
               f"PropertySpec={len(property_spec)} 个性质")

    return {
        "simbad_info": simbad_result,
        "property_spec": property_spec,
        "target_schema": target_schema
    }
