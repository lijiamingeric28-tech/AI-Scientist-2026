"""
运行完整管道

用法：
    python scripts/run_pipeline.py --query "查询文本"
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    """主函数"""
    print("=" * 60)
    print("Scientific Data Pipeline")
    print("=" * 60)

    # TODO: 迁移完成后实现
    # from main_graph.graph import compile_main_pipeline
    #
    # pipeline = compile_main_pipeline()
    # result = pipeline.invoke({
    #     "user_query": "查询示例"
    # })
    # print(result)

    print("\n⚠️  管道尚未完成迁移")
    print("迁移状态:")
    print("  [ ] 子图1: 意图澄清")
    print("  [ ] 子图2: 检索")
    print("  [ ] 子图3: 提取")
    print("  [ ] 子图4: 质检")


if __name__ == "__main__":
    main()
