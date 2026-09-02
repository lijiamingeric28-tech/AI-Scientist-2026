"""
Agent A: Expand_Query_Agent

将意图参数翻译为学术文献检索策略
"""

import logging
from state.retrieval_state import RetrievalState
from tools.expand_query import extract_core_entities, expand_synonyms, build_paper_query

logger = logging.getLogger(__name__)


class StateValidationError(Exception):
    """State验证错误"""
    pass


def expand_query_agent(state: RetrievalState) -> RetrievalState:
    """
    Agent A: Expand_Query_Agent

    将意图参数翻译为学术文献检索策略
    """
    print("\n" + "="*80)
    print("[*] [检索子图 - Agent A] 查询扩展开始")
    print("="*80)

    logger.info("=" * 50)
    logger.info("[Agent A] Expand_Query_Agent started")

    # 读取输入
    intent_params = state.get("intent_params")

    # 输入校验
    if not intent_params:
        logger.error("intent_params is empty")
        raise StateValidationError("intent_params is required")

    print(f"\n>>> 输入参数:")
    print(f"  - 实体: {intent_params.entities}")
    print(f"  - 属性: {intent_params.properties}")
    print(f"  - 条件: {intent_params.conditions}")

    # ===== Node 1: Core Entity Extraction =====
    print(f"\n[步骤 1/3] 提取核心实体和属性")
    logger.info("[Node 1] Starting Core Entity Extraction")

    try:
        extracted = extract_core_entities(intent_params)

        entities = extracted["entities"]
        properties = extracted["properties"]
        conditions = extracted["conditions"]

        print(f"  [+] 提取了 {len(entities)} 个实体, {len(properties)} 个属性")
        logger.info(f"Extracted {len(entities)} entities, {len(properties)} properties")
        logger.debug(f"Entities: {entities}")
        logger.debug(f"Properties: {properties}")
        logger.debug(f"Conditions: {conditions}")

    except Exception as e:
        logger.error(f"Core entity extraction failed: {e}", exc_info=True)
        raise StateValidationError(f"Failed to extract core entities: {e}")

    # ===== Node 2: Synonym Expansion =====
    print(f"\n[步骤 2/3] LLM同义词扩展")
    logger.info("[Node 2] Starting Synonym Expansion")

    try:
        domain = "materials_science"

        print(f"  [AI] 调用LLM扩展同义词（领域: {domain}）")
        logger.debug(f"Calling expand_synonyms with domain={domain}")

        expanded = expand_synonyms(
            entities=entities,
            properties=properties,
            domain=domain
        )

        print(f"  [+] 扩展成功:")
        print(f"    - 实体变体: {len(expanded['expanded_entities'])} 个")
        print(f"    - 属性变体: {len(expanded['expanded_properties'])} 个")

        # 显示扩展结果
        print(f"\n  [LIST] 实体扩展结果: {', '.join(expanded['expanded_entities'][:5])}")
        if len(expanded['expanded_entities']) > 5:
            print(f"     ... 共 {len(expanded['expanded_entities'])} 个")

        print(f"  [LIST] 属性扩展结果: {', '.join(expanded['expanded_properties'][:5])}")
        if len(expanded['expanded_properties']) > 5:
            print(f"     ... 共 {len(expanded['expanded_properties'])} 个")

        logger.info(
            f"Expansion succeeded: "
            f"{len(expanded['expanded_entities'])} entity variants, "
            f"{len(expanded['expanded_properties'])} property variants"
        )
        logger.debug(f"Expanded entities: {expanded['expanded_entities']}")
        logger.debug(f"Expanded properties: {expanded['expanded_properties']}")

    except Exception as e:
        # 降级：使用原词
        print(f"  [!]  LLM扩展失败: {e}")
        print(f"  --> 降级策略: 使用原始词汇")

        logger.warning(f"Synonym expansion failed: {e}, using original terms")
        expanded = {
            "expanded_entities": entities,
            "expanded_properties": properties
        }

    # ===== Node 3: API Parameter Construction =====
    print(f"\n[步骤 3/3] 构建API查询参数")
    logger.info("[Node 3] Starting API Parameter Construction")

    try:
        expanded_entities = expanded["expanded_entities"]
        expanded_properties = expanded["expanded_properties"]

        logger.debug(
            f"Building paper query with "
            f"{len(expanded_entities)} entities, "
            f"{len(expanded_properties)} properties"
        )

        expanded_queries = build_paper_query(
            expanded_entities=expanded_entities,
            expanded_properties=expanded_properties,
            conditions=conditions
        )

        print(f"  [+] API参数构建完成")
        print(f"  [PIN] OpenAlex查询:")
        openalex_query = expanded_queries['openalex']['search']
        if len(openalex_query) > 100:
            print(f"     {openalex_query[:100]}...")
        else:
            print(f"     {openalex_query}")

        logger.info("API parameters constructed successfully")
        logger.debug(f"OpenAlex query: {expanded_queries['openalex']['search'][:100]}...")

    except Exception as e:
        logger.error(f"API parameter construction failed: {e}", exc_info=True)
        raise StateValidationError(f"Failed to build paper query: {e}")

    # 写入输出
    state["expanded_queries"] = expanded_queries

    print(f"\n[OK] [Agent A] 查询扩展完成")
    print("="*80 + "\n")

    logger.info("[Agent A] Expand_Query_Agent completed")
    logger.info("=" * 50)

    return state
