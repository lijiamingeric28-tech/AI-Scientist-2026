"""
检索子图端到端测试

模拟从澄清意图到下载论文的完整流程
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

from subgraphs.retrieval.graph import create_retrieval_graph
from subgraphs.retrieval.state import RetrievalState
from shared.models.clarified_intent import ClarifiedIntent


def test_end_to_end_retrieval():
    """端到端测试：从澄清意图到下载论文"""

    print("\n" + "="*80)
    print("检索子图端到端测试")
    print("="*80)

    # 1. 创建模拟的澄清意图
    print("\n[步骤 1] 创建模拟的澄清意图...")

    intent = ClarifiedIntent(
        entities=["快速射电暴", "FRB"],
        properties=["色散量", "红移"],
        conditions={"时间范围": "2023-2025"}
    )

    print(f"  - 实体: {intent.entities}")
    print(f"  - 属性: {intent.properties}")
    print(f"  - 条件: {intent.conditions}")

    # 2. 准备初始State
    print("\n[步骤 2] 准备初始State...")

    initial_state: RetrievalState = {
        "intent_params": intent,
        "user_query": "快速射电暴的色散量和红移研究"
    }

    print("  - State创建成功")

    # 3. 创建Graph（不启用引用扩展，加快测试速度）
    print("\n[步骤 3] 创建检索子图Graph...")

    graph = create_retrieval_graph(enable_citation_expansion=False)

    print("  - Graph创建成功")
    print("  - 流程: expand_query → search_openalex → search_pubmed → filter_rank → download")
    print("  - 注意: 引用扩展已禁用（加快测试）")

    # 4. 执行Graph
    print("\n[步骤 4] 执行检索子图...")
    print("-" * 80)

    try:
        # 执行完整流程
        final_state = graph.invoke(initial_state)

        print("-" * 80)
        print("\n[步骤 5] 检查执行结果...")

        # 检查各个阶段的输出
        print("\n>>> 查询扩展结果:")
        if "expanded_queries" in final_state:
            openalex_query = final_state["expanded_queries"].get("openalex", {})
            print(f"  - 搜索查询: {openalex_query.get('search', 'N/A')[:80]}...")
            print(f"  - 过滤条件: {openalex_query.get('filter', {})}")
        else:
            print("  - 无结果")

        print("\n>>> OpenAlex检索结果:")
        papers = final_state.get("papers", [])
        print(f"  - 检索到 {len(papers)} 篇论文")
        if papers:
            for idx, paper in enumerate(papers[:3], 1):
                print(f"    [{idx}] {paper.title[:60]}...")
                print(f"        ID: {paper.id} | 引用: {paper.citation_count} | 年份: {paper.year}")

        print("\n>>> PubMed检索结果:")
        pubmed_papers = final_state.get("pubmed_papers", [])
        print(f"  - 检索到 {len(pubmed_papers)} 篇论文")
        if pubmed_papers:
            for idx, paper in enumerate(pubmed_papers[:3], 1):
                print(f"    [{idx}] {paper.title[:60]}...")

        print("\n>>> 过滤排序结果:")
        filtered_papers = final_state.get("filtered_papers", [])
        print(f"  - 过滤后 {len(filtered_papers)} 篇论文")
        if filtered_papers:
            print(f"  - Top 3:")
            for idx, paper in enumerate(filtered_papers[:3], 1):
                print(f"    [{idx}] {paper.title[:60]}...")
                print(f"        评分: {paper.score:.2f} | 引用: {paper.citation_count} | 年份: {paper.year}")

        print("\n>>> 下载结果:")
        if filtered_papers:
            success_count = sum(1 for p in filtered_papers if p.download_status == "success")
            failed_count = sum(1 for p in filtered_papers if p.download_status == "failed")
            skipped_count = sum(1 for p in filtered_papers if p.download_status == "skipped")

            print(f"  - 成功: {success_count} 篇")
            print(f"  - 失败: {failed_count} 篇")
            print(f"  - 跳过: {skipped_count} 篇")

            # 显示成功下载的论文
            success_papers = [p for p in filtered_papers if p.download_status == "success"]
            if success_papers:
                print(f"\n  成功下载的论文(前3篇):")
                for idx, paper in enumerate(success_papers[:3], 1):
                    print(f"    [{idx}] {paper.title[:60]}...")
                    print(f"        本地路径: {paper.local_path}")
                    print(f"        下载来源: {paper.download_source}")
                    print(f"        文件大小: {paper.file_size / 1024:.1f} KB")

                    # 验证文件是否存在
                    if paper.local_path and os.path.exists(paper.local_path):
                        print(f"        ✅ 文件存在")
                    else:
                        print(f"        ❌ 文件不存在")

        print("\n" + "="*80)
        print("✅ 端到端测试完成！")
        print("="*80)

        # 返回最终状态以便进一步检查
        return final_state

    except Exception as e:
        print(f"\n❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    # 运行端到端测试
    final_state = test_end_to_end_retrieval()

    if final_state:
        print("\n[SUCCESS] 检索子图端到端测试成功完成！")

        # 统计信息
        papers = final_state.get("papers", [])
        filtered = final_state.get("filtered_papers", [])

        if filtered:
            success = sum(1 for p in filtered if p.download_status == "success")
            print(f"\n最终统计:")
            print(f"  - 初始检索: {len(papers)} 篇")
            print(f"  - 过滤后: {len(filtered)} 篇")
            print(f"  - 成功下载: {success} 篇")
    else:
        print("\n[FAILED] 测试失败，请检查错误信息")
