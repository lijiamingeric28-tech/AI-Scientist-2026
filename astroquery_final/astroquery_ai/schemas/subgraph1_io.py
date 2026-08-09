"""子图1（意图澄清）接口契约 — 主图 ↔ 子图1

Input：主图投影给子图的键（user_query，原名 original_query，Phase 2 统一）
Output：子图结果中主图消费的键（子图私有键如 chat_history/clarification_turns
       由 Pydantic 默认忽略，不上浮主图 state）

所有字段宽松（Optional/默认值）：验证失败只记 error_log 降级，不阻塞主流程。
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class Sg1Input(BaseModel):
    """主图 → 子图1 的输入契约"""

    model_config = ConfigDict(extra="ignore")

    user_query: str
    """用户原始自然语言查询（主图键名，子图1 原用 original_query）"""

    query_id: str = ""


class Sg1Output(BaseModel):
    """子图1 → 主图的输出契约（主图消费的字段全集）"""

    model_config = ConfigDict(extra="ignore")

    target_entity: Optional[str] = None
    """澄清后的天体名称"""

    requested_properties: List[str] = []
    """用户请求的物理性质列表，空表示"全部" """

    entity_type_hint: str = "unknown"
    """天体类型提示（全系统固定 "unknown"）"""

    user_confirmed: bool = False
    """用户是否确认澄清参数"""

    clarification_status: str = "confirmed"
    """"confirmed" | "modified" | "failed" | "cancelled" """

    query_type: str = "astronomical"
    """"astronomical" | "greeting" | "exit" | "invalid" """

    conversation_history: List[dict] = []
    """完整对话历史（用于追溯）"""

    error_log: List[dict] = []
    """子图内部产生的错误（增量，主图 add reducer 累加）"""
