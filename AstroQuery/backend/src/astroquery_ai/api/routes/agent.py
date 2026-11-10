"""智能体专属交互路由与 SSE 流式管道 (Agent Copilot Routes 2.0)"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from astroquery_ai.agent_harness import AgentController, AgentStore, load_task_bundle
from astroquery_ai.runtime.errors import DomainError

logger = logging.getLogger("web.agent_routes")


def register(app, application, scheduler):
    """装配科研问答智能体交互路由至 FastAPI 应用。"""
    store = AgentStore(application.repository)

    @app.get("/api/tasks/{task_id}/agent/messages")
    def get_agent_messages(task_id: str):
        """获取任务的全部问答历史。"""
        with application.repository.read() as conn:
            task = application.repository.task(conn, task_id)
            src_id = application.history.source(conn, task_id)

        messages = store.get_messages(src_id)
        return {"messages": messages}

    @app.delete("/api/tasks/{task_id}/agent/messages")
    def delete_agent_messages(task_id: str):
        """清空任务的问答历史。"""
        with application.repository.read() as conn:
            task = application.repository.task(conn, task_id)
            src_id = application.history.source(conn, task_id)

        count = store.delete_messages(src_id)
        return {"deleted": True, "count": count}

    @app.post("/api/tasks/{task_id}/agent/chat")
    async def agent_chat_stream(task_id: str, request: Request):
        """流式与科研数据问答智能体进行 ReAct 交互。"""
        with application.repository.read() as conn:
            task = application.repository.task(conn, task_id)
            src_id = application.history.source(conn, task_id)

        body = await request.json()
        user_content = (body.get("content") or body.get("query") or "").strip()
        if not user_content:
            raise HTTPException(400, "提问内容不可为空")

        # 记录用户提问
        store.add_message(src_id, role="user", content=user_content)

        # 加载历史与缓存数据包
        history = store.get_messages(src_id)
        try:
            bundle = load_task_bundle(src_id, application)
        except Exception as exc:
            logger.error("加载任务交付数据快照失败: %s", exc, exc_info=True)
            raise HTTPException(500, f"任务缓存加载失败: {str(exc)}")

        controller = AgentController(bundle, application=application)

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
                        "data": json.dumps(ev_data, ensure_ascii=False),
                    }

                # 交互完成后入库助手回答
                if final_answer_data:
                    store.add_message(
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
                    "data": json.dumps({"error": f"推理执行异常: {str(exc)}"}, ensure_ascii=False),
                }

        return EventSourceResponse(_event_generator())
