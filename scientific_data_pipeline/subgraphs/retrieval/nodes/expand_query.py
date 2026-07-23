"""
Agent A: Expand_Query_Agent (重构版 - 天文学专用)

新流程:
1. 提取核心实体和属性
2. LLM同义词扩展 + 中文翻译
3. LLM Topic智能检测 (1-3个Topics)
4. 构建OpenAlex查询参数（含智能时间解析）

保留: ENABLE_PUBMED开关（当前为False，暂不删除）
"""

import logging
from subgraphs.retrieval.state import RetrievalState
from subgraphs.retrieval.tools.expand_query import (
    extract_core_entities,
    expand_synonyms,
    build_paper_query,
    build_pubmed_query,
    detect_topics_with_llm
)
from config.constants import ENABLE_PUBMED

logger = logging.getLogger(__name__)


class StateValidationError(Exception):
    """State验证错误"""
    pass


def expand_query_agent(state: RetrievalState) -> RetrievalState:
    """
    Agent A: 查询扩展 (重构版 - 天文学专用)

    职责:
    - 将用户意图转换为OpenAlex API查询参数
    - 自动翻译中文术语为英文
    - 智能检测最相关的OpenAlex Topics
    - 智能解析时间范围（默认最近50年）

    输入:
    - intent_params: 意图参数 (entities, properties, conditions)
    - user_query: 用户原始查询

    输出:
    - expanded_queries: {"openalex": {search, filter}}
    """
    print("\n" + "="*80)
    print("[*] [检索子图 - Agent A] 查询扩展开始 (天文学专用)")
    print("="*80)

    logger.info("=" * 50)
    logger.info("[Agent A] Expand_Query_Agent started (Refactored v2)")
    logger.info(f"ENABLE_PUBMED = {ENABLE_PUBMED} (当前禁用)")

    # ========== 读取输入 ==========
    intent_params = state.get("intent_params")
    user_query = state.get("user_query", "")
    query_context = state.get("query_context", {})

    # 调试：输出query_context
    print(f"\n[DEBUG] query_context = {query_context}")
    print(f"[DEBUG] max_papers = {query_context.get('max_papers', 'NOT FOUND')}")

    # 输入验证
    if not intent_params:
        logger.error("intent_params is empty")
        raise StateValidationError("intent_params is required")

    print(f"\n>>> 输入参数:")
    print(f"  - 用户查询: {user_query}")
    print(f"  - 实体: {intent_params.get('entities') if isinstance(intent_params, dict) else intent_params.entities}")
    print(f"  - 属性: {intent_params.get('properties') if isinstance(intent_params, dict) else intent_params.properties}")
    print(f"  - 条件: {intent_params.get('conditions') if isinstance(intent_params, dict) else intent_params.conditions}")

    # ========== 步骤1: 提取核心实体和属性 ==========
    print(f"\n[步骤 1/4] 提取核心实体和属性")
    logger.info("[Step 1/4] Core Entity Extraction")

    try:
        extracted = extract_core_entities(intent_params)

        entities = extracted["entities"]
        properties = extracted["properties"]
        conditions = extracted["conditions"]

        print(f"  [+] 提取了 {len(entities)} 个实体, {len(properties)} 个属性")
        logger.info(f"Extracted {len(entities)} entities, {len(properties)} properties")

    except Exception as e:
        logger.error(f"Core entity extraction failed: {e}", exc_info=True)
        raise StateValidationError(f"Failed to extract core entities: {e}")

    # ========== 步骤2: LLM同义词扩展 + 中文翻译 ==========
    print(f"\n[步骤 2/4] LLM同义词扩展 + 中文翻译")
    logger.info("[Step 2/4] Synonym Expansion + Chinese Translation")

    try:
        expanded = expand_synonyms(
            entities=entities,
            properties=properties,
            domain="astronomy"  # 固定为天文学
        )

        expanded_entities = expanded['expanded_entities']
        expanded_properties = expanded['expanded_properties']

        print(f"  [+] 扩展成功:")
        print(f"    - 实体: {expanded_entities[:3]}{'...' if len(expanded_entities) > 3 else ''} (共{len(expanded_entities)}个)")
        print(f"    - 属性: {expanded_properties[:3]}{'...' if len(expanded_properties) > 3 else ''} (共{len(expanded_properties)}个)")

        logger.info(f"Expanded to {len(expanded_entities)} entity variants, {len(expanded_properties)} property variants")

    except Exception as e:
        logger.warning(f"LLM expansion failed: {e}, using original terms")
        print(f"  [!] LLM扩展失败: {e}, 使用原始词汇")
        expanded_entities = entities
        expanded_properties = properties

    # ========== 步骤3: LLM Topic智能检测 (新增) ==========
    print(f"\n[步骤 3/4] LLM Topic智能检测")
    logger.info("[Step 3/4] LLM Topic Detection")

    topic_ids = []
    try:
        topic_ids = detect_topics_with_llm(
            user_query=user_query,
            entities=expanded_entities,
            properties=expanded_properties
        )

        if topic_ids:
            print(f"  [+] 推荐Topics ({len(topic_ids)}个):")
            for tid in topic_ids:
                print(f"      - {tid}")
            logger.info(f"Detected topics: {topic_ids}")
        else:
            print(f"  [+] 无法确定具体Topic，将使用Subfield: 3103 (Astronomy)")
            logger.info("No specific topics detected, will use Subfield 3103")

    except Exception as e:
        logger.warning(f"Topic detection failed: {e}, falling back to Subfield")
        print(f"  [!] Topic检测失败: {e}, 降级到Subfield过滤")
        topic_ids = []

    # ========== 步骤4: 构建OpenAlex查询参数 ==========
    print(f"\n[步骤 4/4] 构建OpenAlex查询参数（含智能时间解析）")
    logger.info("[Step 4/4] Build OpenAlex Query Parameters (with smart time parsing)")

    try:
        openalex_params = build_paper_query(
            expanded_entities=expanded_entities,
            expanded_properties=expanded_properties,
            conditions=conditions,
            domain="astronomy",
            user_query=user_query,
            topic_ids=topic_ids
        )

        search_query = openalex_params['search']
        filter_dict = openalex_params['filter']
        # 硬编码限制20篇（测试用）
        per_page = 20

        print(f"  [+] 查询参数构建完成")
        print(f"  [QUERY] {search_query[:80]}{'...' if len(search_query) > 80 else ''}")
        print(f"  [FILTER] {filter_dict}")
        print(f"  [PER_PAGE] {per_page}")

        logger.info(f"Built query: {search_query[:100]}...")
        logger.info(f"Filter: {filter_dict}")

    except Exception as e:
        logger.error(f"Query building failed: {e}", exc_info=True)
        raise StateValidationError(f"Failed to build query: {e}")

    # ========== 写入输出 (仅OpenAlex，ENABLE_PUBMED=False) ==========
    expanded_queries = {
        "openalex": {
            "search": search_query,
            "filter": filter_dict,
            "per_page": per_page
        }
    }

    # 注意：ENABLE_PUBMED当前为False，不构建PubMed查询
    if ENABLE_PUBMED:
        print(f"\n  [PIN] PubMed查询: 已禁用（ENABLE_PUBMED=False）")

    state["expanded_queries"] = expanded_queries

    print(f"\n[OK] [Agent A] 查询扩展完成")
    print("="*80 + "\n")

    logger.info("[Agent A] Expand_Query_Agent completed successfully")
    logger.info("=" * 50)

    return state
