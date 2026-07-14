"""
带DEBUG日志的下载测试

启用DEBUG级别日志，查看Unpaywall等来源的详细尝试记录
"""

import sys
from pathlib import Path
import time
import os
import json
import logging
from datetime import datetime

# 设置DEBUG级别日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('debug_download_test.log', encoding='utf-8')
    ]
)

# 添加项目路径
project_path = Path(__file__).parent.parent
sys.path.insert(0, str(project_path))

from pipeline.retrieval.graph import create_retrieval_graph
from models.clarified_intent import ClarifiedIntent

def debug_download_test():
    """带DEBUG日志的下载测试"""

    # 创建带时间戳的输出目录
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_base = Path(__file__).parent / "data" / f"debug_test_{timestamp}"
    papers_dir = output_base / "papers"
    metadata_dir = output_base / "metadata"

    papers_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    # 设置环境变量
    os.environ['TEST_OUTPUT_PAPERS_DIR'] = str(papers_dir)
    os.environ['TEST_OUTPUT_METADATA_DIR'] = str(metadata_dir)

    print("="*80)
    print("DEBUG级别下载测试")
    print("="*80)
    print(f"输出目录: {output_base}")
    print(f"日志文件: debug_download_test.log")
    print("="*80)

    # 创建检索图
    graph = create_retrieval_graph()

    # 简单查询
    query = "graphene mechanical properties"

    # 构造intent_params
    intent_params = ClarifiedIntent(
        entities=["graphene"],
        properties=["mechanical", "properties"],
        conditions={"year": "2020-2024"}
    )

    # 构建输入状态
    input_state = {
        "intent_params": intent_params,
        "query": query,
        "domain": "materials_science",
        "filters": {
            "year_start": 2020,
            "year_end": 2024
        }
    }

    print("\n开始执行检索...")
    start = time.time()

    try:
        output = graph.invoke(input_state)
        elapsed = time.time() - start

        print("\n" + "="*80)
        print("测试完成")
        print("="*80)
        print(f"总耗时: {elapsed:.2f}秒")
        print(f"搜索结果: {len(output.get('papers', []))} 篇")
        print(f"引用扩展: {len(output.get('citation_papers', []))} 篇")
        print(f"过滤后: {len(output.get('filtered_papers', []))} 篇")

        # 保存元数据
        filtered_papers = output.get('filtered_papers', [])

        print(f"\n保存元数据到: {metadata_dir}")

        download_sources = {}

        for paper in filtered_papers:
            metadata_file = metadata_dir / f"{paper.id}.json"

            # 保存元数据
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(paper.model_dump(), f, indent=2, ensure_ascii=False)

            # 统计下载来源
            if paper.download_status == "success":
                source = paper.download_source or "unknown"
                download_sources[source] = download_sources.get(source, 0) + 1

        print(f"已保存 {len(filtered_papers)} 个元数据文件")

        # 分析下载来源
        print("\n" + "="*80)
        print("下载来源统计")
        print("="*80)

        success_count = sum(1 for p in filtered_papers if p.download_status == "success")

        if success_count > 0:
            print(f"\n成功下载: {success_count} 篇\n")
            for source, count in sorted(download_sources.items(), key=lambda x: x[1], reverse=True):
                percentage = (count / success_count) * 100
                print(f"  {source:15s}: {count:3d} 篇  ({percentage:.1f}%)")

            # 如果使用了unpaywall或core
            if 'unpaywall' in download_sources or 'core' in download_sources:
                print("\n" + "="*80)
                print("!!! 发现使用了Unpaywall/CORE !!!")
                print("="*80)

                for paper in filtered_papers:
                    if paper.download_status == "success" and paper.download_source in ['unpaywall', 'core']:
                        print(f"\n[{paper.download_source.upper()}] {paper.title[:60]}...")
                        print(f"  ID: {paper.id}")
                        print(f"  DOI: {paper.doi}")
        else:
            print("\n没有成功下载的论文")

        print("\n" + "="*80)
        print(f"详细日志已保存到: debug_download_test.log")
        print("="*80)

        return True

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = debug_download_test()
    sys.exit(0 if success else 1)
