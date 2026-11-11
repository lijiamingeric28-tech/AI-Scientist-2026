"""
knowledge.py — API endpoints for the incremental and user-preference knowledge base system.

Routes:
- GET    /api/knowledge
- GET    /api/knowledge/graph
- GET    /api/knowledge/{entry_id}
- POST   /api/knowledge
- PUT    /api/knowledge/{entry_id}
- DELETE /api/knowledge/{entry_id}
- POST   /api/knowledge/{entry_id}/preference
- POST   /api/knowledge/{entry_id}/restore
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import FastAPI, Query, Request
from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.scheduler import Scheduler
from astroquery_ai.science.user_knowledge_store import UserKnowledgeStore

logger = logging.getLogger("web.knowledge_routes")


def register(app: FastAPI, application: Application, scheduler: Scheduler) -> None:
    store = UserKnowledgeStore.get_instance()

    @app.get("/api/knowledge")
    def list_knowledge(
        category: Optional[str] = None,
        property_id: Optional[str] = None,
        user_only: bool = False,
        preferred_only: bool = False,
        keyword: Optional[str] = None,
        limit: int = Query(default=100, ge=-1, le=2000),
        offset: int = Query(default=0, ge=0),
    ):
        """Query knowledge entries with optional category, property, user, preference, and keyword filters."""
        return store.list_entries(
            category=category,
            property_id=property_id,
            user_only=user_only,
            preferred_only=preferred_only,
            keyword=keyword,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/knowledge/graph")
    def get_knowledge_graph(
        category: Optional[str] = None,
        property_id: Optional[str] = None,
        user_only: bool = False,
        preferred_only: bool = False,
        keyword: Optional[str] = None,
    ):
        """Return graph topology { nodes, edges, categories } for the knowledge graph visualizer."""
        return store.get_graph(
            category=category,
            property_id=property_id,
            user_only=user_only,
            preferred_only=preferred_only,
            keyword=keyword,
        )

    @app.get("/api/knowledge/{entry_id}")
    def get_knowledge_entry(entry_id: str):
        """Retrieve a specific knowledge entry by unique entry_id."""
        entry = store.get_entry(entry_id)
        if not entry:
            raise DomainError("KNOWLEDGE_ENTRY_NOT_FOUND", f"未找到理论知识条目「{entry_id}」", 404)
        return entry

    @app.post("/api/knowledge")
    async def create_knowledge_entry(request: Request):
        """Create a new user custom theoretical knowledge entry."""
        try:
            body = await request.json()
        except Exception:
            raise DomainError("INVALID_JSON", "请求体JSON格式错误", 422)

        if not isinstance(body, dict):
            raise DomainError("INVALID_PAYLOAD", "请求体必须为JSON对象", 422)

        entry = store.create_user_entry(body)
        return entry

    @app.put("/api/knowledge/{entry_id}")
    async def update_knowledge_entry(entry_id: str, request: Request):
        """Update an existing user entry, or fork-override a base knowledge entry."""
        try:
            body = await request.json()
        except Exception:
            raise DomainError("INVALID_JSON", "请求体JSON格式错误", 422)

        if not isinstance(body, dict):
            raise DomainError("INVALID_PAYLOAD", "请求体必须为JSON对象", 422)

        entry = store.update_entry(entry_id, body)
        return entry

    @app.delete("/api/knowledge/{entry_id}")
    def delete_knowledge_entry(entry_id: str, restore: bool = False):
        """Delete a user entry, or restore/soft-delete a base entry."""
        if restore:
            return store.restore_default(entry_id)
        return store.delete_entry(entry_id)

    @app.post("/api/knowledge/{entry_id}/restore")
    def restore_knowledge_entry(entry_id: str):
        """Explicitly restore a modified or overridden base entry back to default state."""
        return store.restore_default(entry_id)

    @app.post("/api/knowledge/{entry_id}/preference")
    async def set_knowledge_preference(entry_id: str, request: Request):
        """Toggle preferred, neutral, or deprioritized state with extra ranking boost."""
        try:
            body = await request.json()
        except Exception:
            raise DomainError("INVALID_JSON", "请求体JSON格式错误", 422)

        if not isinstance(body, dict):
            raise DomainError("INVALID_PAYLOAD", "请求体必须为JSON对象", 422)

        pref = body.get("preference")
        if pref is None and "preferred" in body:
            pref = "preferred" if body["preferred"] else "neutral"

        weight_boost = body.get("weight_boost")
        return store.set_preference(entry_id, pref or "neutral", weight_boost)
