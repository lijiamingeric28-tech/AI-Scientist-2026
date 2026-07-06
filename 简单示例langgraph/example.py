

import os
from typing import Annotated
from typing_extensions import TypedDict

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langgraph.graph import StateGraph, START          
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command, interrupt

# -------- 环境变量和模型 ---------
os.environ["OPENAI_API_KEY"] = ""
os.environ["TAVILY_API_KEY"] = ""

llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.environ["OPENAI_API_KEY"],
    base_url="https://api.deepseek.com/v1"
)

# -------- 状态 ---------
class State(TypedDict):
    messages: Annotated[list, add_messages]

# -------- 工具定义 ---------
@tool
def human_assistance(query: str) -> str:
    """Request assistance from a human."""
    human_response = interrupt({"query": query})
    return human_response["data"]

tool = TavilySearch(max_results=2, api_key=os.environ["TAVILY_API_KEY"])
tools = [tool, human_assistance]
llm_with_tools = llm.bind_tools(tools)

# -------- 构建图 ---------
graph_builder = StateGraph(State)

def chatbot(state: State):
    message = llm_with_tools.invoke(state["messages"])
    # 移除断言或改为更宽松的检查（可选）
    # assert(len(message.tool_calls) <= 1)
    return {"messages": [message]}

graph_builder.add_node("chatbot", chatbot)
tool_node = ToolNode(tools=tools)
graph_builder.add_node("tools", tool_node)

graph_builder.add_conditional_edges(
    "chatbot",
    tools_condition,
)
graph_builder.add_edge("tools", "chatbot")
graph_builder.add_edge(START, "chatbot")   # 现在 START 已导入

memory = MemorySaver()
graph = graph_builder.compile(checkpointer=memory)

# -------- 流式输出（支持中断/恢复）--------
def stream_graph_updates(user_input: str, thread_id: str = "1"):
    config = {"configurable": {"thread_id": thread_id}}
    
    # 初始输入
    inputs = {"messages": [{"role": "user", "content": user_input}]}
    
    while True:
        try:
            for event in graph.stream(inputs, config, stream_mode="updates"):
                # 处理每个节点的输出
                for node_name, value in event.items():
                    # 如果有新消息，打印出来
                    if "messages" in value:
                        last_msg = value["messages"][-1]
                        if hasattr(last_msg, "content") and last_msg.content:
                            print(f"[{node_name}] Assistant:", last_msg.content)
                # 如果没有中断，正常结束
            break  # 正常结束循环
        except Exception as e:
            # 检查是否是中断异常（LangGraph 会抛出特定异常）
            if "interrupt" in str(e).lower() or hasattr(e, "interrupts"):
                # 处理中断：从异常中提取中断信息
                interrupts = getattr(e, "interrupts", [])
                if interrupts:
                    # 取第一个中断
                    interrupt_data = interrupts[0].value
                    print(f"\n[系统] 请求人工协助: {interrupt_data['query']}")
                    # 获取用户输入作为响应
                    human_response = input("请输入您的回答: ")
                    # 使用 Command(resume=...) 恢复执行
                    inputs = Command(resume={"data": human_response})
                    continue  # 继续循环，重新 stream
                else:
                    # 其他异常，无法恢复
                    raise
            else:
                # 非中断异常，抛出
                raise

# -------- 交互循环 ---------
while True:
    try:
        user_input = input("User: ")
        if user_input.lower() in ["quit", "exit", "q"]:
            print("Goodbye!")
            break
        stream_graph_updates(user_input)
    except KeyboardInterrupt:
        break
    except Exception as e:
        print("Error:", e)
        break