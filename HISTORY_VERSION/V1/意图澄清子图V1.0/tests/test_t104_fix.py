#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
T104 修复验证脚本
"""
from pipeline.intent.graph import create_intent_clarification_graph

print("=" * 60)
print("T104 修复验证测试")
print("=" * 60)

query = "找超新星的数据"
print(f"\n输入查询: {query}")

graph = create_intent_clarification_graph()

# 模拟用户输入
initial_state = {
    "original_query": query
}

# 注意：这里会在追问环节阻塞，需要手动输入
print("\n开始执行...")
print("提示：系统应该会追问'您想了解超新星的哪些数据？'\n")

try:
    result = graph.invoke(initial_state)

    print("\n" + "=" * 60)
    print("执行完成")
    print("=" * 60)
    print(f"用户确认: {result.get('user_confirmed')}")
    print(f"提取参数: {result.get('extracted_parameters')}")
    print(f"追问轮次: {result.get('clarification_turns', 0)}")

except KeyboardInterrupt:
    print("\n\n测试中断")

