"""询问性质列表节点（答复就地解读 2026-09-03）

历史问题（2026-09-03 实跑暴露）：ask_properties 仅把答复记入 chat_history 后经
固定边回 initial_parse —— initial_parse 用首轮分类器 classify_query_type 评判
澄清答复，而"全部"/直接回车等系统建议答法无天文特征词，被误判 invalid →
polite_reject 整次查询失败（0 来源 0 记录）。

现在：interrupt 恢复点在节点内就地解读答复，不再回 initial_parse 全量重分类：
  - 空（回车）/ 全部 / 所有 / 都行 … → 查全部（requested_properties 留空，
    语义由 P1 性质标准化兜底为默认性质集，见 property_standardization.py）
  - 退出关键词（算了/不查了/取消/放弃…）→ clarification_status=cancelled 优雅终止
  - 其余 → LLM 提取性质（顺带支持改写天体）；解析不出 → 礼貌重问
    （受 clarification max_turns 限制；超限回退"查全部"，由 final_confirm 再次
    让用户确认/修改/取消，绝不 polite_reject 结束任务）
"""

import logging
from datetime import datetime

from langgraph.types import interrupt

from ..state import IntentClarificationState
from ..config import config
from ..utils import extract_entity_and_properties
from ..utils.llm_utils import _keyword_hit

logger = logging.getLogger(__name__)

# 问句里明确向用户建议的"查全部"表达（含口语变体）
_ALL_MARKERS = ("全部性质", "所有性质", "全都要", "全部都要", "能查的都要")
_ALL_KEYWORDS = ("全部", "所有", "都行", "全查", "all", "everything")


def _is_all_request(answer: str) -> bool:
    """回车空答 / "全部"、"所有"、"都行" 等 → 查全部。

    词边界判定复用 classify 的 _keyword_hit（独立 token 命中）；"查全部性质"
    这类嵌在短语里的复合表达用显式 marker 补兜底。
    """
    text = answer.strip()
    if not text:
        return True
    low = text.lower()
    if any(_keyword_hit(low, kw) for kw in _ALL_KEYWORDS):
        return True
    return any(m in text for m in _ALL_MARKERS)


def _exit_requested(answer: str) -> bool:
    """澄清轮内退出意图检测（规则先行，与首轮 classify 的退出检测同口径）。"""
    low = answer.strip().lower()
    return any(_keyword_hit(low, kw) for kw in config.exit_keywords)


def _question_for(entity: str, is_reask: bool, turns: int) -> str:
    """首问与重问的提问文案（重问携带上一轮未识别的提示）。"""
    if is_reask:
        return f"""
抱歉，我未能从您的回答中识别出要查询的性质。

请重新告诉我要查询 {entity} 的哪些物理性质：

您可以：
1. 输入具体性质名称（例如："距离和红移"）
2. 输入 "全部" 或 "所有" 查询所有可用性质
3. 直接按回车键跳过，我们将返回所有可用数据
4. 输入 "取消" 放弃本次查询

请输入：
"""
    return f"""
您想查询 {entity} 的哪些物理性质？

您可以：
1. 输入具体性质名称（例如："距离和红移"）
2. 输入 "全部" 或 "所有" 查询所有可用性质
3. 直接按回车键跳过，我们将返回所有可用数据
4. 输入 "取消" 放弃本次查询

请输入：
"""


def ask_properties(state: IntentClarificationState) -> IntentClarificationState:
    """
    询问性质列表节点
    当天体名称已提取，但性质列表为空时，主动询问用户想查询哪些性质；
    收到答复后就地解读（查全部 / 具体性质 / 取消 / 无法识别重问）。

    Args:
        state: 当前状态

    Returns:
        IntentClarificationState: 更新后的状态
    """
    target_entity = state.get("target_entity", "该天体")
    turns = state.get("clarification_turns", 0)
    is_reask = state.get("properties_asked", False) and bool(
        state.get("chat_history", [])
    )
    logger.info(
        f"[ask_properties] 询问 {target_entity} 的性质 (轮次 {turns + 1})"
    )

    question = _question_for(target_entity, is_reask=is_reask, turns=turns)

    payload = {
        "type": "ask_properties",
        "title": "选择查询性质",  # Web 结构化（契约 D3-2/D5-2）
        "text": f"\n{config.ui['separator']}\n{question}\n{config.ui['separator']}\n\n您的选择：",
        "question": question,
        "target_entity": target_entity,
    }
    if is_reask:
        # 与 final_confirm M-09 重发同款：携带 error 提示
        payload["error"] = "未能识别上一轮回答中的性质，请按上方提示重新输入"
    user_input = interrupt(payload)
    if user_input is None:
        user_input = ""
    answer = str(user_input).strip()
    logger.debug(f"[ask_properties] 用户输入: {answer}")

    # 更新对话历史（与 greeting_handler/ask_entity 同约定：每轮一问一答）
    chat_history = state.get("chat_history", [])
    chat_history.append({
        "role": "assistant",
        "content": question,
        "timestamp": datetime.now().isoformat()
    })
    chat_history.append({
        "role": "user",
        "content": answer if answer else "[直接回车]",
        "timestamp": datetime.now().isoformat()
    })
    state["chat_history"] = chat_history

    # 标记已询问过性质
    state["properties_asked"] = True

    # ── 答复就地解读（不再回 initial_parse 全量重分类）──
    state["clarification_turns"] = turns + 1
    resolved = False

    if _exit_requested(answer):
        # 澄清轮内显式取消 → 优雅终止（主图走 cancelled → 最终聚合，非 failed）
        state["clarification_status"] = "cancelled"
        state["user_confirmed"] = False
        state["exit_intent_detected"] = True
        chat_history.append({
            "role": "assistant",
            "content": "好的，已取消本次查询。如需帮助随时告诉我。",
            "timestamp": datetime.now().isoformat()
        })
        logger.info("[ask_properties] 用户在澄清轮内取消查询")
        state["properties_resolved"] = False
        return state

    if _is_all_request(answer):
        # 查全部：性质留空列表（state 契约：空列表 = 查询所有性质），P1 兜底默认集
        state["requested_properties"] = []
        resolved = True
        logger.info("[ask_properties] 答复为查全部 (properties 留空)")
    else:
        # 具体性质：LLM 提取（与首轮 extraction 同函数，可顺带改写天体）
        parsed = extract_entity_and_properties(
            user_input=answer,
            chat_history=chat_history,
        )
        props = parsed.get("requested_properties", [])
        entity = parsed.get("target_entity")

        if isinstance(props, list) and props:
            state["requested_properties"] = [p for p in props if isinstance(p, str)]
            resolved = True
            logger.info(
                f"[ask_properties] 提取到性质: {state['requested_properties']}"
            )
        if isinstance(entity, str) and entity and entity != state.get("target_entity"):
            # 顺带支持改写天体（与 initial_parse 同能力）；未给性质时对新天体重问
            state["target_entity"] = entity
            logger.info(f"[ask_properties] 天体改写为: {entity}")
        if not resolved:
            logger.info("[ask_properties] 答复未解析出性质，待重问")

    if not resolved:
        max_turns = config.clarification['max_turns']
        if state["clarification_turns"] >= max_turns:
            # 重问超限回退"查全部"（用户仍可在 final_confirm 修改/取消）
            logger.warning(
                f"[ask_properties] 重问超限 ({max_turns} 轮)，回退查全部"
            )
            state["requested_properties"] = []
            resolved = True

    state["properties_resolved"] = resolved
    logger.info(
        f"[ask_properties] 询问完成 resolved={resolved} "
        f"turns={state['clarification_turns']}"
    )
    return state
