"""
简化测试 - 只测试检索功能，不下载PDF

用于快速验证API和检索功能是否正常
"""

import sys
from pathlib import Path
import time
from datetime import datetime

# 添加项目路径
project_path = Path(__file__).parent.parent
sys.path.insert(0, str(project_path))

from models.clarified_intent import ClarifiedIntent
from pipeline.retrieval.agents.expand_query import expand_query_agent
from pipeline.retrieval.agents.paper_search import paper_search_agent
from pipeline.retrieval.agents.citation_expansion import citation_expansion_agent
from pipeline.retrieval.agents.filter_rank import filter_rank_agent

def simple_test():
    """简化测试 - 不下载PDF"""

    print("="*80)
    print("简化检索测试（无下载）")
    print("="*80)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    # 构造测试输入
    query = "graphene mechanical properties"

    intent_params = ClarifiedIntent(
        entities=["graphene"],
        properties=["mechanical", "properties"],
        conditions={"year": "2020-2024"}
    )

    state = {
        "intent_params": intent_params,
        "query": query
    }

    print(f"\n查询: {query}")
    print(f"实体: {intent_params.entities}")
    print(f"属性: {intent_params.properties}")
    print(f"条件: {intent_params.conditions}")

    # Agent A: 查询扩展
    print("\n" + "="*80)
    print("[Agent A] 查询扩展")
    print("="*80)
    start = time.time()
    try:
        state = expand_query_agent(state)
        elapsed = time.time() - start
        print(f"[OK] 完成 ({elapsed:.2f}秒)")
        print(f"扩展查询: {state.get('expanded_queries', {}).get('search_query', 'N/A')[:100]}...")
    except Exception as e:
        print(f"[ERROR] 失败: {e}")
        return False

    # Agent B: 论文搜索
    print("\n" + "="*80)
    print("[Agent B] 论文搜索")
    print("="*80)
    start = time.time()
    try:
        state = paper_search_agent(state)
        elapsed = time.time() - start
        papers = state.get('papers', [])
        print(f"[OK] 完成 ({elapsed:.2f}秒)")
        print(f"搜索到: {len(papers)} 篇论文")

        if papers:
            print(f"\n前3篇论文:")
            for i, paper in enumerate(papers[:3], 1):
                print(f"  [{i}] {paper.title[:60]}...")
                print(f"      引用数: {paper.citation_count}, 年份: {paper.year}")
    except Exception as e:
        print(f"[ERROR] 失败: {e}")
        return False

    # Agent C: 引用扩展
    print("\n" + "="*80)
    print("[Agent C] 引用扩展")
    print("="*80)
    start = time.time()
    try:
        state = citation_expansion_agent(state)
        elapsed = time.time() - start
        citation_papers = state.get('citation_papers', [])
        print(f"[OK] 完成 ({elapsed:.2f}秒)")
        print(f"引用扩展: {len(citation_papers)} 篇论文")
    except Exception as e:
        print(f"[ERROR] 失败: {e}")
        return False

    # Agent E: 过滤排序
    print("\n" + "="*80)
    print("[Agent E] 过滤排序")
    print("="*80)
    start = time.time()
    try:
        state = filter_rank_agent(state)
        elapsed = time.time() - start
        filtered_papers = state.get('filtered_papers', [])
        print(f"[OK] 完成 ({elapsed:.2f}秒)")
        print(f"过滤后: {len(filtered_papers)} 篇论文")

        if filtered_papers:
            print(f"\nTop 5 论文:")
            for i, paper in enumerate(filtered_papers[:5], 1):
                print(f"  [{i}] {paper.title[:60]}...")
                print(f"      引用数: {paper.citation_count}, 年份: {paper.year}")
    except Exception as e:
        print(f"[ERROR] 失败: {e}")
        return False

    # 最终统计
    print("\n" + "="*80)
    print("测试总结")
    print("="*80)
    print(f"[OK] 所有步骤成功完成")
    print(f"\n统计:")
    print(f"  搜索结果: {len(state.get('papers', []))} 篇")
    print(f"  引用扩展: {len(state.get('citation_papers', []))} 篇")
    print(f"  过滤后: {len(state.get('filtered_papers', []))} 篇")
    print(f"\n注: 此测试跳过了PDF下载步骤")
    print("="*80)

    return True


if __name__ == "__main__":
    success = simple_test()
    sys.exit(0 if success else 1)
