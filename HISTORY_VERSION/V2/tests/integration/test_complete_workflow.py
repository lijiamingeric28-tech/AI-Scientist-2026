"""
完整工具链测试

验证从用户查询 → 意图澄清 → 检索下载的完整流程
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

from main_graph.graph import compile_main_pipeline
from main_graph.state import MainState


def test_complete_workflow():
    """测试完整工作流"""

    print("\n" + "="*80)
    print("完整工具链测试：用户查询 → 意图澄清 → 检索 → 下载")
    print("="*80)

    # 1. 创建主图
    print("\n[步骤 1] 编译主图...")
    main_graph = compile_main_pipeline()
    print("  [OK] 主图编译成功")

    # 2. 准备输入
    print("\n[步骤 2] 准备用户查询...")
    initial_state: MainState = {
        "user_query": "快速射电暴的色散量和红移研究，最近3年的",
        "query_context": {
            "domain": "astronomy",
            "language": "zh"
        }
    }
    print(f"  - 用户查询: {initial_state['user_query']}")
    print(f"  - 领域: {initial_state['query_context']['domain']}")

    # 3. 执行主图
    print("\n[步骤 3] 执行主图...")
    print("-" * 80)

    try:
        final_state = main_graph.invoke(initial_state)

        print("-" * 80)
        print("\n[步骤 4] 检查执行结果...")

        # 检查意图澄清结果
        print("\n>>> 意图澄清结果:")
        if "intent_params" in final_state:
            intent = final_state["intent_params"]
            print(f"  - 实体: {intent.entities}")
            print(f"  - 属性: {intent.properties}")
            print(f"  - 条件: {intent.conditions}")
            print(f"  - 妥协标记: {final_state.get('compromise_flag', False)}")
        else:
            print("  [FAIL] 无意图澄清结果")

        # 检查检索结果
        print("\n>>> 检索结果:")
        papers = final_state.get("papers", [])
        print(f"  - 检索到 {len(papers)} 篇论文")

        if papers:
            print(f"\n  Top 5论文:")
            for idx, paper in enumerate(papers[:5], 1):
                print(f"    [{idx}] {paper.title[:60]}...")
                print(f"        评分: {paper.score:.2f} | 引用: {paper.citation_count} | 年份: {paper.year}")
                if paper.download_status == "success":
                    print(f"        [OK] 下载成功: {paper.local_path}")
                    print(f"        来源: {paper.download_source} | 大小: {paper.file_size/1024:.1f} KB")
                else:
                    print(f"        [FAIL] 下载失败: {paper.download_error}")

        # 统计下载结果
        print("\n>>> 下载统计:")
        if papers:
            success_count = sum(1 for p in papers if p.download_status == "success")
            failed_count = sum(1 for p in papers if p.download_status == "failed")
            skipped_count = sum(1 for p in papers if p.download_status == "skipped")

            print(f"  - 成功: {success_count} 篇")
            print(f"  - 失败: {failed_count} 篇")
            print(f"  - 跳过: {skipped_count} 篇")
            print(f"  - 成功率: {success_count/len(papers)*100:.1f}%")

            # 验证文件存在
            success_papers = [p for p in papers if p.download_status == "success"]
            if success_papers:
                print(f"\n  验证本地文件:")
                verified = 0
                for paper in success_papers[:3]:
                    if paper.local_path and os.path.exists(paper.local_path):
                        verified += 1
                        print(f"    [OK] {os.path.basename(paper.local_path)}")
                    else:
                        print(f"    [FAIL] {paper.id} - 文件不存在")

                print(f"  文件验证: {verified}/{min(3, len(success_papers))} 通过")

        print("\n" + "="*80)
        print("[OK] 完整工具链测试完成！")
        print("="*80)

        return final_state

    except Exception as e:
        print(f"\n[FAIL] 执行失败: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    print("\n" + "="*80)
    print("科学数据管道 - 完整工具链测试")
    print("子图1（意图澄清）+ 子图2（检索下载）")
    print("="*80)

    final_state = test_complete_workflow()

    if final_state:
        print("\n[SUCCESS] 完整工具链测试成功！")

        # 最终统计
        papers = final_state.get("papers", [])
        if papers:
            success = sum(1 for p in papers if p.download_status == "success")
            print(f"\n[STAT] 最终统计:")
            print(f"  - 检索论文: {len(papers)} 篇")
            print(f"  - 成功下载: {success} 篇")
            print(f"  - 成功率: {success/len(papers)*100:.1f}%")
    else:
        print("\n[FAILED] 测试失败，请检查错误信息")
