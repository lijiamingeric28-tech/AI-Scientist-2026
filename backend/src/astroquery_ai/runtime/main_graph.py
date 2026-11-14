"""One short-job LangGraph. All authoritative data lives in Repository."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class DispatchState(TypedDict):
    job: dict
    completed_job_id: str


def create_main_graph(dispatch):
    async def execute(state: DispatchState):
        await dispatch(state["job"])
        return {"completed_job_id": state["job"]["job_id"]}

    graph = StateGraph(DispatchState)
    graph.add_node("execute_short_job", execute)
    graph.add_edge(START, "execute_short_job")
    graph.add_edge("execute_short_job", END)
    return graph.compile()
