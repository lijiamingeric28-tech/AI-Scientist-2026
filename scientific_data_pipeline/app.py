"""
app.py - 科学数据提取管道测试应用

运行完整的4子图管道：
1. 意图澄清
2. 论文检索
3. 数据提取
4. 质量控制

用法:
    python app.py                           # 交互式输入
    python app.py "查找近三年FRB的DM色散量数据"  # 命令行参数

输出:
    - final_output: 质检后的结构化数据
    - 导出文件: subgraphs/quality/output/{date}/
"""

import sys
sys.path.insert(0, '.')

from dotenv import load_dotenv
load_dotenv()

from main_graph.graph import compile_main_pipeline
from main_graph.state import MainState


def run_pipeline(query: str):
    """
    运行完整的4子图管道

    Args:
        query: 用户查询
    """

    print('='*80)
    print(' '*25 + '科学数据提取管道')
    print('='*80)

    print(f'\n用户查询: {query}')
    print(f'最大论文数: 20篇')
    print()

    # 构建输入
    input_state: MainState = {
        "user_query": query,
        "query_context": {
            "max_papers": 20,  # 硬编码为20篇
            "enable_citation_expansion": False,
            "enable_pubmed": False,
        }
    }

    # 编译管道
    print('编译4子图管道...')
    pipeline = compile_main_pipeline()
    print(f'管道节点: {list(pipeline.nodes.keys())}')
    print()

    # 执行管道
    print('='*80)
    print('开始执行管道（完整的4个子图）')
    print('='*80)
    print()

    try:
        result = pipeline.invoke(input_state)

        # 输出结果
        print()
        print('='*80)
        print('执行结果')
        print('='*80)

        # 子图1: 意图澄清
        print('\n【子图1: 意图澄清】')
        if 'intent_params' in result:
            intent = result['intent_params']
            print(f'  实体: {intent.get("entities", [])}')
            print(f'  属性: {intent.get("properties", [])}')
            print(f'  条件: {intent.get("conditions", {})}')
        else:
            print('  ❌ 未执行')

        # 子图2: 检索
        print('\n【子图2: 检索】')
        if 'papers' in result:
            papers = result['papers']
            print(f'  论文总数: {len(papers)}篇')

            # papers是PaperMetadata对象列表，不是dict
            downloaded = 0
            for p in papers:
                if hasattr(p, 'local_path') and p.local_path:
                    downloaded += 1

            print(f'  下载成功: {downloaded}篇')
        else:
            print('  ❌ 未执行')

        # 子图3: 提取
        print('\n【子图3: 提取】')
        if 'grounded_data' in result:
            gd = result['grounded_data']
            records = gd.get('records', [])
            sources = gd.get('sources', [])
            print(f'  提取记录数: {len(records)}条')
            print(f'  源文献数: {len(sources)}篇')
            if 'verification_rate' in result:
                print(f'  验证率: {result["verification_rate"]*100:.1f}%')
        else:
            print('  ❌ 未执行')

        # 子图4: 质检
        print('\n【子图4: 质检】')
        if 'final_output' in result:
            final = result['final_output']
            records = final.get('records', [])
            sources = final.get('sources', [])
            print(f'  质检后记录数: {len(records)}条')
            print(f'  质检后源文献数: {len(sources)}篇')

            if 'quality_summary' in result:
                qs = result['quality_summary']
                export_path = qs.get("export_path", "N/A")
                if export_path != "N/A":
                    print(f'  导出路径: {export_path}')

                # 显示质量报告
                quality_report = qs.get('quality_report', {})
                if quality_report:
                    scoring = quality_report.get('quality_scoring', {})
                    if scoring:
                        print(f'  质量评分: {scoring.get("overall_score", 0):.4f}')
                        print(f'  质量等级: {scoring.get("quality_level", "N/A")}')
                        print(f'  置信度: {scoring.get("calibrated_confidence", 0):.4f}')
        else:
            print('  ❌ 未执行或未输出final_output')

        print()
        print('='*80)
        print('管道执行成功！')
        print('='*80)

        # 数据完整性检查
        print('\n数据完整性检查:')
        if 'grounded_data' in result and 'final_output' in result:
            input_count = len(result['grounded_data'].get('records', []))
            output_count = len(result['final_output'].get('records', []))
            print(f'  输入记录: {input_count}条')
            print(f'  输出记录: {output_count}条')
            if input_count == output_count:
                print('  ✅ 数据无丢失')
            else:
                print(f'  ⚠️  数据有变化 ({output_count - input_count:+d})')

        return True

    except Exception as e:
        print()
        print('='*80)
        print('执行失败')
        print('='*80)
        print(f'错误: {e}')
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函数"""

    # 检查命令行参数
    if len(sys.argv) > 1:
        # 从命令行读取查询
        query = ' '.join(sys.argv[1:])
        print(f'\n使用命令行参数: {query}\n')
    else:
        # 交互式输入
        print()
        print('='*80)
        print(' '*25 + '科学数据提取管道')
        print('='*80)
        print()
        print('示例查询:')
        print('  - 查找近三年FRB的DM色散量数据')
        print('  - 获取2020年后脉冲星的自转周期')
        print('  - 搜索黑洞质量的观测数据')
        print()

        try:
            query = input('请输入您的查询 (或按Ctrl+C退出): ').strip()
        except (KeyboardInterrupt, EOFError):
            print('\n\n程序已取消')
            return False

        if not query:
            print('\n错误: 查询不能为空')
            return False

        print()

    # 执行管道
    success = run_pipeline(query)
    return success


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
