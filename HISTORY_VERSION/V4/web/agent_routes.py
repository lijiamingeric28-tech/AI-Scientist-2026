"""智能体专属交互路由与 SSE 流式管道 (Agent Copilot Routes)"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from astroquery_ai.agent_harness import AgentController, load_task_bundle
from .task_store import TaskStore

logger = logging.getLogger("web.agent_routes")

router = APIRouter(prefix="/api/tasks/{task_id}/agent", tags=["agent"])


class AgentChatRequest(BaseModel):
    content: Optional[str] = None
    query: Optional[str] = None


def register_agent_routes(app, store: TaskStore, output_dir: str):
    """装配路由至 FastAPI 应用。"""

    @router.get("/messages")
    async def get_agent_messages(task_id: str):
        """获取任务的全部问答历史。"""
        # 回放任务映射
        t = store.get_task(task_id)
        if not t:
            raise HTTPException(404, "任务不存在")
        src_id = t.get("replay_of") or task_id
        messages = store.get_agent_messages(src_id)
        return {"messages": messages}

    @router.delete("/messages")
    async def delete_agent_messages(task_id: str):
        """清空任务的问答历史。"""
        t = store.get_task(task_id)
        if not t:
            raise HTTPException(404, "任务不存在")
        src_id = t.get("replay_of") or task_id
        count = store.delete_agent_messages(src_id)
        return {"deleted": True, "count": count}

    @router.post("/chat")
    async def agent_chat_stream(task_id: str, req: AgentChatRequest):
        """流式与科研数据问答智能体进行 ReAct 交互。"""
        t = store.get_task(task_id)
        if not t:
            raise HTTPException(404, "任务不存在")
        src_id = t.get("replay_of") or task_id

        user_content = (req.content or req.query or "").strip()
        if not user_content:
            raise HTTPException(400, "提问内容不可为空")

        # 记录用户提问
        store.add_agent_message(src_id, role="user", content=user_content)

        # 加载历史与缓存数据包
        history = store.get_agent_messages(src_id)
        try:
            bundle = load_task_bundle(src_id, db_path=store._db, output_dir=output_dir)
        except Exception as exc:
            logger.error("加载任务缓存数据失败: %s", exc)
            raise HTTPException(500, f"任务缓存加载失败: {str(exc)}")

        controller = AgentController(bundle)

        async def _event_generator():
            try:
                final_answer_data = None
                async for event in controller.run_react_stream(history, user_content):
                    ev_type = event["event"]
                    ev_data = event["data"]
                    if ev_type == "agent_done":
                        final_answer_data = ev_data

                    yield {
                        "event": ev_type,
                        "data": json.dumps(ev_data, ensure_ascii=False)
                    }

                # 任务完成后入库助手回答
                if final_answer_data:
                    store.add_agent_message(
                        src_id,
                        role="assistant",
                        content=final_answer_data.get("content", ""),
                        thought_steps=final_answer_data.get("thought_steps", []),
                        citations=final_answer_data.get("citations", []),
                    )
            except Exception as exc:
                logger.error("智能体流式执行发生异常: %s", exc, exc_info=True)
                yield {
                    "event": "error",
                    "data": json.dumps({"error": f"推理执行异常: {str(exc)}"}, ensure_ascii=False)
                }

        return EventSourceResponse(_event_generator())

    app.include_router(router)
