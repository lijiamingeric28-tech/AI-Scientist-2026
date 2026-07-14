"""
下载来源分析脚本

分析已下载的PDF文件，确定它们的下载来源
"""

import sys
from pathlib import Path
import json

# 添加项目路径
project_path = Path(__file__).parent.parent
sys.path.insert(0, str(project_path))

from models.paper_metadata import PaperMetadata

def analyze_download_sources():
    """分析下载来源"""

    print("="*80)
    print("下载来源分析")
    print("="*80)

    # 查找最近下载的PDF
    papers_dir = Path(__file__).parent / "data" / "papers"
    metadata_dir = Path(__file__).parent / "data" / "metadata"

    print(f"\n查找目录: {papers_dir.absolute()}")

    if not papers_dir.exists():
        print(f"错误: {papers_dir} 不存在")
        return

    # 获取所有PDF
    pdf_files = list(papers_dir.glob("*.pdf"))
    print(f"\n找到 {len(pdf_files)} 个PDF文件")

    # 统计来源
    sources = {}

    # 读取元数据
    for pdf_file in pdf_files:
        paper_id = pdf_file.stem
        metadata_file = metadata_dir / f"{paper_id}.json"

        if metadata_file.exists():
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    source = data.get('download_source', 'unknown')
                    sources[source] = sources.get(source, 0) + 1
            except Exception as e:
                print(f"读取元数据失败 {paper_id}: {e}")

    # 打印统计
    print("\n" + "="*80)
    print("下载来源统计")
    print("="*80)

    total = sum(sources.values())

    if not sources:
        print("\n未找到下载来源信息（元数据可能不包含此字段）")
        return

    print(f"\n总计: {total} 篇PDF\n")

    for source, count in sorted(sources.items(), key=lambda x: x[1], reverse=True):
        percentage = (count / total) * 100
        print(f"  {source:15s}: {count:3d} 篇  ({percentage:.1f}%)")

    print("\n" + "="*80)

    # 如果有unpaywall或core来源，列出详细信息
    if 'unpaywall' in sources or 'core' in sources:
        print("\n[重要] 发现使用了Unpaywall/CORE!")
        print("="*80)

        for pdf_file in pdf_files:
            paper_id = pdf_file.stem
            metadata_file = metadata_dir / f"{paper_id}.json"

            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        source = data.get('download_source', 'unknown')

                        if source in ['unpaywall', 'core']:
                            title = data.get('title', 'N/A')
                            doi = data.get('doi', 'N/A')
                            print(f"\n[{source.upper()}] {title[:60]}...")
                            print(f"  ID: {paper_id}")
                            print(f"  DOI: {doi}")
                except:
                    pass
    else:
        print("\n[信息] 本次测试未使用Unpaywall/CORE")
        print("="*80)
        print("\n可能原因:")
        print("  1. OpenAlex的pdf_url和oa_url已经满足需求")
        print("  2. 失败的论文没有DOI，无法查询Unpaywall")
        print("  3. Unpaywall也没有这些论文的开放版本")


if __name__ == "__main__":
    analyze_download_sources()
