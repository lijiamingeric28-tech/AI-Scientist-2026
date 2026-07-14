"""
快速单次测试脚本

用于快速验证检索子图的单个查询

使用方法:
    python quick_test.py

或自定义查询:
    python quick_test.py --query "your query here"
"""

import sys
from pathlib import Path
import time
import argparse
import os
from datetime import datetime

# 添加项目路径
project_path = Path(__file__).parent.parent
sys.path.insert(0, str(project_path))

from pipeline.retrieval.graph import create_retrieval_graph
from models.clarified_intent import ClarifiedIntent


def quick_test(query, year_start=2020, year_end=2024, domain="materials_science"):
    """
    快速测试单个查询

    Args:
        query: 查询字符串
        year_start: 起始年份
        year_end: 结束年份
        domain: 领域
    """
    # 创建带时间戳的输出目录
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_base = Path(__file__).parent / "data" / f"test_run_{timestamp}"
    papers_dir = output_base / "papers"
    metadata_dir = output_base / "metadata"

    papers_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    # 设置环境变量，让pipeline使用这个目录
    os.environ['TEST_OUTPUT_PAPERS_DIR'] = str(papers_dir)
    os.environ['TEST_OUTPUT_METADATA_DIR'] = str(metadata_dir)

    print("="*80)
    print("检索子图快速测试")
    print("="*80)
    print(f"查询: {query}")
    print(f"年份: {year_start}-{year_end}")
    print(f"领域: {domain}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"输出目录: {output_base}")
    print("="*80)

    # 创建检索图
    print("\n[1/2] 初始化检索图...")
    graph = create_retrieval_graph()

    # 构造intent_params
    words = query.lower().split()
    mid = len(words) // 2
    entities = words[:mid] if mid > 0 else [query]
    properties = words[mid:] if mid > 0 else ["properties"]

    intent_params = ClarifiedIntent(
        entities=entities,
        properties=properties,
        conditions={
            "year": f"{year_start}-{year_end}"
        }
    )

    # 构建输入状态
    input_state = {
        "intent_params": intent_params,
        "query": query,
        "domain": domain,
        "filters": {
            "year_start": year_start,
            "year_end": year_end
        }
    }

    # 执行检索
    print("\n[2/2] 执行检索流程...")
    print("-"*80)

    start = time.time()
    try:
        output = graph.invoke(input_state)
        elapsed = time.time() - start

        print("-"*80)
        print("\n" + "="*80)
        print("测试结果")
        print("="*80)

        # 打印结果
        print(f"\n[OK] 测试成功完成")
        print(f"\n耗时: {elapsed:.2f}秒")

        print(f"\n[统计]")
        print(f"  搜索结果: {len(output.get('papers', []))} 篇")
        print(f"  引用扩展: {len(output.get('citation_papers', []))} 篇")
        print(f"  过滤后: {len(output.get('filtered_papers', []))} 篇")

        filtered_papers = output.get('filtered_papers', [])
        if filtered_papers:
            print(f"\n[过滤后论文前5篇]")
            for idx, paper in enumerate(filtered_papers[:5], 1):
                print(f"\n  [{idx}] {paper.title}")
                print(f"      引用数: {paper.citation_count} | 年份: {paper.year} | 评分: {paper.score:.2f}")
                print(f"      ID: {paper.id}")
                if paper.doi:
                    print(f"      DOI: {paper.doi}")

        downloaded = output.get('downloaded_papers', [])
        if downloaded:
            print(f"\n[下载情况]")
            print(f"  成功下载: {len(downloaded)} 篇")
            success = sum(1 for p in downloaded if p.get('pdf_path'))
            print(f"  下载成功率: {success}/{len(downloaded)} ({success/len(downloaded)*100:.1f}%)")

        print("\n" + "="*80)
        print("[OK] 测试完成")
        print("="*80)

        return True

    except Exception as e:
        elapsed = time.time() - start

        print("-"*80)
        print("\n" + "="*80)
        print("测试失败")
        print("="*80)
        print(f"\n[ERROR] 发生错误")
        print(f"  错误: {e}")
        print(f"  耗时: {elapsed:.2f}秒")

        import traceback
        print(f"\n[详细错误]")
        traceback.print_exc()

        print("\n" + "="*80)

        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="检索子图快速测试")
    parser.add_argument(
        '--query',
        default='graphene mechanical properties',
        help='查询字符串 (默认: graphene mechanical properties)'
    )
    parser.add_argument(
        '--year-start',
        type=int,
        default=2020,
        help='起始年份 (默认: 2020)'
    )
    parser.add_argument(
        '--year-end',
        type=int,
        default=2024,
        help='结束年份 (默认: 2024)'
    )
    parser.add_argument(
        '--domain',
        default='materials_science',
        help='领域 (默认: materials_science)'
    )

    args = parser.parse_args()

    # 执行测试
    success = quick_test(
        query=args.query,
        year_start=args.year_start,
        year_end=args.year_end,
        domain=args.domain
    )

    # 返回退出码
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
