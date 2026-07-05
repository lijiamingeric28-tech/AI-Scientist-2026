# LangGraph基本知识（一个python库用于实现基础的ai代理）(实际可用它搭建智能体的运行框架)
# 大概了解了langgraph是干什么的，7.5
来自网页：https://www.datacamp.com/tutorial/langgraph-agents?utm_source=chatgpt.com
状态、节点、边、内存——并使用 ReAct 模式、自定义工具和持久状态管理构建可扩展的 AI 代理。

LangGraph 是一个基于图的框架，用于构建能够通过相互连接的步骤进行推理、规划和行动的 AI 代理。它的独特之处在于它让我们能够轻松创建循环、分支的工作流程，其中每个节点都可以运行 LLM、工具或函数——同时自动管理状态。这使得 LangGraph 非常适合构建需要记忆、错误处理和实时决策的复杂、健壮的多代理系统。
在这个教程中，我将带你了解 LangGraph 的基础知识和高级特性，从理解其核心组件到构建具有状态管理和工具增强功能的 AI 代理。如果你对使用 LangGraph 构建多代理系统感兴趣，请务必查看我们的实践课程。你也可以在下方观看我们关于构建 LangGraph 代理的视频教程。

## LangGraph 基础知识
让我们先讨论 LangGraph 的基本构建模块。这些元素使我们能够构建结构化、具有状态管理和可扩展性的工作流，用于构建高级 AI 代理。
### State  状态
状态是一个在图中流动的共享内存对象。它存储所有相关信息，例如消息、变量、中间结果和决策历史。LangGraph 自动管理状态，使开发更高效。
为了补充状态，还有更高级的支持功能，如检查点、线程本地内存和跨会话持久化。在整个执行过程中，状态会持续更新.
### Node 节点
一个节点是工作流中的一个单一功能单元。它可以执行多种操作，例如：
Invoking a large language model (LLM)
调用大型语言模型（LLM）
Calling a tool or API
调用工具或 API
Running a custom Python function
运行自定义的 Python 函数
Routing logic or branching decisions
路由逻辑或分支决策
Each node takes in the current state and returns an updated state
每个节点接收当前状态并返回更新后的状态

### 边和条件边
边定义了节点之间的转换。它们决定了图的控制流，并可以支持：

Static connections (for linear progression)
静态连接（用于线性进展）
Cyclical paths (for iterative behaviors)
循环路径（用于迭代行为）
Dynamic branching (based on state conditions - created through Conditional Edges)
动态分支（基于状态条件 - 通过条件边创建）

边缘对于协调复杂的智能体行为至关重要。

### 图和状态图
LangGraph 中的图定义了智能体工作流程的结构，它由节点和边连接而成。

StateGraph 是一种特殊的图，它在执行过程中维护和更新共享状态。它支持上下文感知的决策和跨步骤的持久记忆。我们可以将其视为 State 和 Graph 的融合。

### 工具和工具节点
一个工具是代理可以调用的任何外部或内部函数，例如网络搜索、计算器或自定义实用程序。工具有两种类型：


内置工具：Langchain 预制且可立即使用的工具，可在文档中访问。

自定义工具：我们可以自己制作并在应用程序中使用工具（通过装饰器和 DocString 分配完成——这将在稍后的代码中展示）。

一个 ToolNode 是一个专门用于在图中执行工具的节点类型。它允许我们开发者无需编写额外的包装逻辑即可集成工具。我们可以将其视为 Tool 和 Node 的融合。

### 消息类型
消息是结构化数据元素（例如用户输入、系统输出、中间响应等），它们在图中移动并存储在状态中。它们提供了可追溯性、记忆和上下文，以帮助智能体做出更明智的决策。

LangGraph 中有多个 MessageTypes：

HumanMessage：表示来自用户的输入。这是在代理的图中开始或继续对话时最常用的消息类型。
AIMessage：表示由底层语言模型生成的响应。这些响应被存储起来以保持对话记忆并指导未来的行动。
系统消息：向大型语言模型提供上下文或行为设置说明（例如，“你是我的个人助理。”）。此消息会影响模型的响应方式。
ToolMessage：封装了工具的输出。当您的代理依赖于外部操作（如计算或搜索）来决定其下一步行动时，这些至关重要。
移除消息：用于从状态中编程删除或撤销先前添加的消息。这对于错误纠正或修剪不相关的上下文很有帮助。
BaseMessage: LangChain 和 LangGraph 中所有消息类型的父类。每个特定的消息类型——如 HumanMessage 、 AIMessage 或 SystemMessage ——都继承自 BaseMessage 。

### LangGraph 代理
举例：
```python
from typing import TypedDict, List
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from dotenv import load_dotenv
from typing import TypedDict
#类型定义
class Student(TypedDict):
name: str
grade: float
s1: Student = {"name": "Sam", "grade": 92.5}

load_dotenv() # Obtaining over secret keys
# Creation of the state using a Typed Dictionary
class AgentState(TypedDict):
messages: List[HumanMessage] # We are going to be storing Human Messages (the user input) as a list of messages
llm = ChatOpenAI(model="gpt-4o") # Our model choice
# This is an action - the underlying function of our node
def process(state: AgentState) -> AgentState:
response = llm.invoke(state["messages"])
    print(f"\nAI: {response.content}")
    return state
graph = StateGraph(AgentState) # Initialization of a Graph
graph.add_node("process_node", process) # Adding nodes
graph.add_edge(START, "process_node") # Adding edges
graph.add_edge("process_node", END)
agent = graph.compile() # Compiling the graph

user_input = input("Enter: ")
while user_input != "exit":
agent.invoke({"messages": [HumanMessage(content=user_input)]})
user_input = input("Enter: ")
```


### ReAct代理
ReAct Agents（推理与行动代理）在工业中非常常见，因为它们易于创建且功能强大。由于它们非常普遍，LangGraph 提供了一种内置方法，我们可以利用它来创建这类代理。
```python
tools = [GmailToolkit()] # We are using the Inbuilt Gmail tool
llm = ChatOllama(model="qwen2.5:latest") # Leveraging Ollama Models
agent = create_react_agent(
    model = llm, # Choice of the LLM
    tools = tools, # Tools we want our LLM to have
    name = "email_agent", # Name of our agent
    prompt = "You are my AI assistant that has access to certain tools. Use the tools to help me with my tasks.", # System Prompt
)
```

如上所述，在创建自定义工具时，有两件主要的事情很重要：
```python
@tool
def send_email(email_address: str, email_content: str) -> str:
    """
Sends an email to a specified recipient with the given content.
Args:
email_address (str): The recipient's email address (e.g., 'example@example.com')
email_content (str): The body of the email message to be sent
Returns:
str: A confirmation message indicating success or failure
Example:
        >>> send_email('john.doe@example.com', 'Hello John, just checking in!')
'Email successfully sent to john.doe@example.com'
"""
    # Tool Logic goes here
    return "Done!"
```
工具自定义方式：
Decorator
装饰器：这告诉 LangGraph 这个特定的函数是一个专用函数——一个工具。
Docstring
文档字符串：这需要提供工具对 LLM 的作用背景。提供每个参数的示例和描述很有用，因为这使工具调用更加健壮。

状态增长的重构函数
在定义更复杂、更健壮的代理系统时，使用 Reducer 函数或简单地使用 reducers 是一个好主意。 reducers 是数据注解，它们确保每次节点返回消息时，都会追加到状态中的现有列表，而不是覆盖之前的值。这使得我们的状态能够逐步构建上下文。


### LangGraph 中的内存管理
在本节中，我们将重点关注每个代理的核心组件 - 内存。内存对于代理来说非常重要，因为它提供了使其更加健壮和可靠所需的上下文。让我们探索我们可以以不同的方式管理我们代理中的内存。
#### 外部检查点存储
状态是 LangGraph 中最重要的元素，自然而然地，有多种方法可以将状态存储在外部。一些流行的外部存储方式包括：
SQLite
PostgreSQL
Amazon S3
Azure Blob Storage  Azure Blob 存储
Google Cloud Storage  Google 云存储
Mem0

```python
from langgraph.checkpoint.sqlite import SqliteSaver
memory = SqliteSaver.from_conn_string(":memory:") # This is for connecting to the SQLite database
graph = graph_builder.compile(checkpointer=memory) # Compiling graph with checkpointer as SQLite backend
```
所有这些都是为了存储和更新状态。现在让我们来看看如何有效地使用和管理该状态，特别是 messages 列表，随着对话的继续，它会变得相当大。

LangGraph 为短期和长期记忆提供了原生支持。让我们来探讨这些。

#### 短期记忆
短期记忆允许我们的代理在会话期间记住消息历史，使其适用于多轮对话。
```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph

checkpointer = InMemorySaver()

builder = StateGraph(...)
graph = builder.compile(checkpointer=checkpointer)


# Invoking the Graph with our message
agent_graph.invoke(
    {"messages": [{"role": "user", "content": "What's the weather today?"}]},
    {"configurable": {"thread_id": "session_42"}},
)
```

#### 长期记忆
长期记忆跨越多个会话，非常适合记住名字、目标或设置等跨会话的重要事项。
```python
from langgraph.store.memory import InMemoryStore
from langgraph.graph import StateGraph

long_term_store = InMemoryStore()
builder = StateGraph(...)
agent = builder.compile(store=long_term_store)
```
然而，由于我们的对话可能会变得很长，我们需要一种方法来限制我们的消息历史。这就是修剪的作用所在。

#### 修剪
在以下示例中，我们从消息历史的前面移除标记（由于行： strategy="first" ），以便在修剪后，我们最多保留 150 个标记。
```python
from langchain_core.messages.utils import trim_messages, count_tokens_approximately

trimmed = trim_messages(
        messages=state["messages"],
        strategy="first",  # remove the messages from beginning
        token_counter=count_tokens_approximately,
        max_tokens=150
    )
```

总体而言，LangGraph 是一个强大的库，它提供了一种结构化和可扩展的方法来构建智能体系统。将建模逻辑视为节点和边的图，具有共享状态和持久内存，使我们能够开发出能够在时间中推理、交互和适应的健壮智能体。

随着系统复杂性的增加，该框架提供了管理内存、协调工具使用和维护长期上下文所需的工具——同时保持模块化和可扩展性。

核心组件现已就位，您已具备设计和部署能够处理实际工作流程的健壮 AI 代理的能力。