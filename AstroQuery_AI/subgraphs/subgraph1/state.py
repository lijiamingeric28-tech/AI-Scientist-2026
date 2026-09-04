"""状态定义模块"""

from typing import TypedDict, Optional, List
from typing_extensions import NotRequired


class IntentClarificationState(TypedDict):
    """
    意图澄清子图的状态定义（极简版）
    """

    # ===== 输入字段（从主图或用户传入） =====
    user_query: str
    """用户的原始自然语言查询，必填（Phase 2 统一：原 original_query）"""

    query_id: NotRequired[str]
    """查询唯一标识符（UUID），在主图中生成"""

    # ===== 工作字段（子图内部使用） =====
    chat_history: NotRequired[List[dict]]
    """
    对话历史记录
    格式：[{"role": "user"|"assistant", "content": "...", "timestamp": "..."}]
    默认：[]
    """

    clarification_turns: NotRequired[int]
    """
    当前追问轮次计数器
    范围：0 <= turns <= 3
    默认：0
    """

    properties_asked: NotRequired[bool]
    """
    是否已经询问过 requested_properties
    防止重复询问
    默认：False
    """

    # ===== 提取结果字段 =====
    target_entity: NotRequired[Optional[str]]
    """
    天体名称或标识符（必填）
    示例："M31", "Gaia DR3 5854013331201520640", "仙女座星系"
    默认：None
    """

    requested_properties: NotRequired[List[str]]
    """
    用户希望查询的物理性质列表（可选）
    示例：["distance", "metallicity", "redshift"]
    空列表表示查询所有性质
    默认：[]
    """

    entity_type_hint: NotRequired[str]
    """
    天体类型推断（全系统默认值）
    固定值："unknown"
    说明：用户表示暂不需要此字段进行分类，统一使用默认值
    """

    # ===== 控制字段（用于路由决策） =====
    query_type: NotRequired[str]
    """
    查询类型分类
    可选值：
    - "astronomical": 天文学查询
    - "greeting": 寒暄/闲聊
    - "exit": 退出意图
    - "invalid": 非天文查询
    默认："astronomical"
    """

    is_clear: NotRequired[bool]
    """
    意图是否已完全澄清
    - True: target_entity 存在，可以进入确认阶段
    - False: 仍需继续澄清
    默认：False
    """

    exit_intent_detected: NotRequired[bool]
    """
    是否检测到用户想要退出
    识别关键词：算了、不查了、退出、取消、放弃等
    默认：False
    """

    properties_resolved: NotRequired[bool]
    """
    ask_properties 答复是否已就地解读确定（2026-09-03 方向1）
    - True: 已确定（查全部 / 具体性质 / 重问超限回退），可进 final_confirm
    - False: 答复未解析出性质，需礼貌重问
    默认：False
    """

    # ===== 输出字段（传递给下游子图） =====
    user_confirmed: NotRequired[bool]
    """
    用户是否确认最终参数
    - True: 用户确认，下游可以继续
    - False: 用户拒绝/取消，下游应终止流程
    默认：False
    """

    clarification_status: NotRequired[str]
    """
    澄清状态
    可选值：
    - "confirmed": 用户明确确认
    - "modified":  用户要求修改并重新输入
    - "failed": 澄清失败
    - "cancelled": 用户取消
    默认："confirmed"
    """

    conversation_history: NotRequired[List[dict]]
    """
    完整对话历史（用于下游追溯和分析）
    与 chat_history 相同，但作为最终输出字段
    """
