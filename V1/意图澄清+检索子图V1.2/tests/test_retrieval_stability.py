"""
检索子图系统稳定性测试脚本

使用方法:
    python test_retrieval_stability.py

    或指定测试套件:
    python test_retrieval_stability.py --suite p0
    python test_retrieval_stability.py --suite all
"""

import sys
from pathlib import Path
import time
import json
from datetime import datetime
import argparse

# 添加项目路径
project_path = Path(__file__).parent.parent
sys.path.insert(0, str(project_path))

from pipeline.retrieval.graph import create_retrieval_graph
from state.retrieval_state import RetrievalState
from models.clarified_intent import ClarifiedIntent


def create_intent_params_from_query(query, year_start=2020, year_end=2024):
    """
    从查询字符串构造intent_params

    Args:
        query: 查询字符串
        year_start: 起始年份
        year_end: 结束年份

    Returns:
        ClarifiedIntent对象
    """
    # 简单解析查询，提取关键词作为entities和properties
    words = query.lower().split()

    # 假设前半部分是实体，后半部分是属性
    mid = len(words) // 2
    entities = words[:mid] if mid > 0 else [query]
    properties = words[mid:] if mid > 0 else ["properties"]

    return ClarifiedIntent(
        entities=entities,
        properties=properties,
        conditions={
            "year": f"{year_start}-{year_end}"
        }
    )


class RetrievalSystemTester:
    """检索子图系统测试器"""

    def __init__(self):
        self.graph = create_retrieval_graph()
        self.results = []
        self.test_start_time = datetime.now()

    def run_test(self, test_id, test_name, input_state, expected_behavior):
        """
        运行单个测试

        Args:
            test_id: 测试ID（如"1.1"）
            test_name: 测试名称
            input_state: 输入状态字典
            expected_behavior: 预期行为字典

        Returns:
            测试结果字典
        """
        print(f"\n{'='*80}")
        print(f"[TEST {test_id}] {test_name}")
        print(f"{'='*80}")
        print(f"输入查询: {input_state.get('query', 'N/A')}")

        # 自动构造intent_params（如果没有提供）
        if 'intent_params' not in input_state:
            filters = input_state.get('filters', {})
            year_start = filters.get('year_start', 2020)
            year_end = filters.get('year_end', 2024)
            input_state['intent_params'] = create_intent_params_from_query(
                input_state.get('query', ''),
                year_start,
                year_end
            )

        result = {
            "test_id": test_id,
            "test_name": test_name,
            "success": False,
            "start_time": datetime.now().isoformat(),
            "errors": [],
            "warnings": [],
            "metrics": {},
            "input": {
                "query": input_state.get('query', 'N/A'),
                "domain": input_state.get('domain', 'N/A')
            }
        }

        try:
            # 执行检索流程
            start = time.time()
            output = self.graph.invoke(input_state)
            elapsed = time.time() - start

            # 收集指标
            metrics = {
                "elapsed_time": round(elapsed, 2),
                "papers_searched": len(output.get("papers", [])),
                "citations_expanded": len(output.get("citation_papers", [])),
                "papers_after_merge": 0,  # 需要从日志获取
                "papers_filtered": len(output.get("filtered_papers", [])),
                "papers_downloaded": len(output.get("downloaded_papers", []))
            }

            result["metrics"] = metrics
            result["output"] = {
                "papers": len(output.get("papers", [])),
                "citation_papers": len(output.get("citation_papers", [])),
                "filtered_papers": len(output.get("filtered_papers", []))
            }

            # 打印指标
            print(f"\n[指标]")
            print(f"  搜索结果: {metrics['papers_searched']} 篇")
            print(f"  引用扩展: {metrics['citations_expanded']} 篇")
            print(f"  过滤后: {metrics['papers_filtered']} 篇")
            print(f"  下载成功: {metrics['papers_downloaded']} 篇")
            print(f"  总耗时: {metrics['elapsed_time']}秒")

            # 验证预期行为
            validation_result = self.validate_output(output, expected_behavior)
            result["success"] = validation_result["success"]
            result["warnings"] = validation_result["warnings"]

            if result["success"]:
                print(f"\n[结果] PASS")
            else:
                print(f"\n[结果] FAIL")
                for warning in result["warnings"]:
                    print(f"  警告: {warning}")

        except Exception as e:
            result["errors"].append(str(e))
            print(f"\n[结果] ERROR")
            print(f"  错误: {e}")
            import traceback
            traceback.print_exc()

        finally:
            result["end_time"] = datetime.now().isoformat()
            self.results.append(result)

        return result

    def validate_output(self, output, expected):
        """
        验证输出是否符合预期

        Args:
            output: 实际输出
            expected: 预期行为字典
                - min_papers: 最少论文数
                - max_papers: 最多论文数
                - no_errors: 是否不允许错误
                - min_citations: 最少引用扩展数
                - allow_empty: 是否允许空结果

        Returns:
            dict: {"success": bool, "warnings": []}
        """
        warnings = []

        # 验证必需字段存在
        if not output:
            warnings.append("输出为空")
            return {"success": False, "warnings": warnings}

        required_fields = ["papers", "filtered_papers"]
        for field in required_fields:
            if field not in output:
                warnings.append(f"缺少必需字段: {field}")

        # 验证最少论文数
        if "min_papers" in expected:
            actual = len(output.get("filtered_papers", []))
            if actual < expected["min_papers"]:
                warnings.append(f"论文数不足: 期望≥{expected['min_papers']}, 实际{actual}")

        # 验证最多论文数
        if "max_papers" in expected:
            actual = len(output.get("filtered_papers", []))
            if actual > expected["max_papers"]:
                warnings.append(f"论文数过多: 期望≤{expected['max_papers']}, 实际{actual}")

        # 验证引用扩展
        if "min_citations" in expected:
            actual = len(output.get("citation_papers", []))
            if actual < expected["min_citations"]:
                warnings.append(f"引用扩展不足: 期望≥{expected['min_citations']}, 实际{actual}")

        # 验证允许空结果
        if not expected.get("allow_empty", False):
            if len(output.get("filtered_papers", [])) == 0:
                warnings.append("结果为空但预期不为空")

        # 判断成功
        success = len(warnings) == 0

        return {"success": success, "warnings": warnings}

    def generate_report(self, output_file="test_results/stability_test_report.json"):
        """生成测试报告"""
        print(f"\n{'='*80}")
        print("测试报告")
        print(f"{'='*80}")

        total = len(self.results)
        passed = sum(1 for r in self.results if r["success"])
        failed = total - passed

        print(f"\n测试执行时间: {self.test_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"总测试数: {total}")
        print(f"通过: {passed}")
        print(f"失败: {failed}")
        print(f"通过率: {passed/total*100:.1f}%" if total > 0 else "N/A")

        print(f"\n详细结果:")
        for r in self.results:
            status = "[PASS]" if r["success"] else "[FAIL]"
            print(f"  {status} Test {r['test_id']}: {r['test_name']}")
            if r["errors"]:
                for err in r["errors"]:
                    print(f"         错误: {err}")
            if r["warnings"]:
                for warn in r["warnings"]:
                    print(f"         警告: {warn}")

        # 性能统计
        if self.results:
            times = [r["metrics"].get("elapsed_time", 0) for r in self.results if r["metrics"]]
            if times:
                print(f"\n性能统计:")
                print(f"  平均耗时: {sum(times)/len(times):.2f}秒")
                print(f"  最快: {min(times):.2f}秒")
                print(f"  最慢: {max(times):.2f}秒")

        # 保存JSON报告
        report = {
            "test_time": self.test_start_time.isoformat(),
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": passed/total*100 if total > 0 else 0
            },
            "tests": self.results
        }

        report_file = Path(output_file)
        report_file.parent.mkdir(parents=True, exist_ok=True)
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"\n详细报告已保存: {report_file}")

        return report


def run_p0_tests(tester):
    """运行P0级别测试（必须通过）"""
    print("\n" + "="*80)
    print("P0 测试套件 - 必须通过")
    print("="*80)

    # Test 1.1: 标准材料科学查询
    tester.run_test(
        test_id="1.1",
        test_name="标准材料科学查询",
        input_state={
            "query": "graphene mechanical properties",
            "domain": "materials_science",
            "filters": {
                "year_start": 2020,
                "year_end": 2024
            }
        },
        expected_behavior={
            "min_papers": 5,
            "min_citations": 20,
            "no_errors": True
        }
    )

    # Test 3.1: 引用扩展成功率
    tester.run_test(
        test_id="3.1",
        test_name="引用扩展成功率",
        input_state={
            "query": "deep learning materials discovery",
            "domain": "materials_science",
            "filters": {
                "year_start": 2021,
                "year_end": 2024
            }
        },
        expected_behavior={
            "min_papers": 10,
            "min_citations": 30,
            "no_errors": True
        }
    )


def run_p1_tests(tester):
    """运行P1级别测试（重要）"""
    print("\n" + "="*80)
    print("P1 测试套件 - 重要")
    print("="*80)

    # Test 1.2: 窄领域查询
    tester.run_test(
        test_id="1.2",
        test_name="窄领域查询",
        input_state={
            "query": "topological insulators Bi2Se3 quantum transport",
            "domain": "materials_science",
            "filters": {
                "year_start": 2023,
                "year_end": 2024
            }
        },
        expected_behavior={
            "min_papers": 1,
            "allow_empty": False
        }
    )

    # Test 1.3: 宽泛查询
    tester.run_test(
        test_id="1.3",
        test_name="宽泛查询",
        input_state={
            "query": "machine learning materials",
            "domain": "materials_science",
            "filters": {
                "year_start": 2020,
                "year_end": 2024
            }
        },
        expected_behavior={
            "min_papers": 20,
            "no_errors": True
        }
    )

    # Test 2.3: 零结果查询
    tester.run_test(
        test_id="2.3",
        test_name="零结果处理",
        input_state={
            "query": "xyzabcdef123nonsense materials quantum",
            "domain": "materials_science"
        },
        expected_behavior={
            "allow_empty": True,
            "no_errors": True
        }
    )


def run_p2_tests(tester):
    """运行P2级别测试（建议）"""
    print("\n" + "="*80)
    print("P2 测试套件 - 建议")
    print("="*80)

    # Test 2.1: 极短查询
    tester.run_test(
        test_id="2.1",
        test_name="极短查询",
        input_state={
            "query": "graphene",
            "domain": "materials_science"
        },
        expected_behavior={
            "min_papers": 5,
            "no_errors": True
        }
    )

    # Test 2.4: 特殊字符查询
    tester.run_test(
        test_id="2.4",
        test_name="特殊字符查询",
        input_state={
            "query": "Cu-Zn alloy (70/30) @ 300°C",
            "domain": "materials_science"
        },
        expected_behavior={
            "min_papers": 1,
            "no_errors": True
        }
    )


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="检索子图稳定性测试")
    parser.add_argument(
        '--suite',
        choices=['p0', 'p1', 'p2', 'all'],
        default='p0',
        help='测试套件选择 (默认: p0)'
    )
    parser.add_argument(
        '--output',
        default='test_results/stability_test_report.json',
        help='报告输出路径'
    )

    args = parser.parse_args()

    print("="*80)
    print("检索子图系统稳定性测试")
    print("="*80)
    print(f"测试套件: {args.suite.upper()}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    tester = RetrievalSystemTester()

    # 根据选择运行测试
    if args.suite == 'p0':
        run_p0_tests(tester)
    elif args.suite == 'p1':
        run_p0_tests(tester)
        run_p1_tests(tester)
    elif args.suite == 'p2':
        run_p0_tests(tester)
        run_p1_tests(tester)
        run_p2_tests(tester)
    elif args.suite == 'all':
        run_p0_tests(tester)
        run_p1_tests(tester)
        run_p2_tests(tester)

    # 生成报告
    tester.generate_report(args.output)

    # 返回退出码
    failed = sum(1 for r in tester.results if not r["success"])
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
