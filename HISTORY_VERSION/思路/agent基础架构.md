# agent理论知识
参考文献：
1. https://developer.nvidia.com/blog/introduction-to-llm-agents/?utm_source=chatgpt.com
2. https://developer.nvidia.com/blog/building-your-first-llm-agent-application/
3. https://hld.handbook.academy/curriculum/ai-ml-system-design/llm-serving-architecture/
4. https://newsletter.diamant-ai.com/p/your-first-ai-agent-simpler-than
## agent的定义
LLM 服务架构涵盖了生成器：连续批处理、KV 缓存、延迟计算。RAG 管道涵盖了检索作为增强。一个代理增加了第三层：自主性。模型决定下一步做什么。

Anthropic 做出了明确的区分：工作流是 LLM 和工具通过预定义的代码路径进行编排的系统，而代理是 LLM 动态指导自身进程和工具使用的系统 [1:1] 。大多数使用 LangChain 或 LangGraph 构建的生产系统都属于该分类法中的工作流。指导原则非常直接：“如果你可以用确定性管道解决，那就用那个” 

最小可行代理有四个组件：
一个可以发出结构化工具调用的 LLM
一组具有 JSON-schema 定义的工具
一个草稿板（不断增长的消息历史）记忆功能。
一个循环，将工具结果反馈回去并检查是否终止

其他所有事情，反思，规划，内存层级，多智能体协调，都是在这个核心之上的优化

## ReAct 模式：思考-行动-观察
