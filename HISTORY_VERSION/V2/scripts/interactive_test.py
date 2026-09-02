"""
意图澄清子图 - 交互式测试

让用户输入查询，实时查看意图澄清的结果
"""

import sys
sys.path.insert(0, '.')

from dotenv import load_dotenv
load_dotenv()

from subgraphs.intent_clarification.graph import compile_intent_clarification_graph
import json


def interactive_test_intent():
    """交互式测试意图澄清子图"""

    print('=' * 70)
    print(' ' * 15 + '意图澄清子图 - 交互式测试')
    print('=' * 70)
    print()
    print('这是一个交互式测试工具，您可以输入查询并查看意图澄清的结果。')
    print()
    print('提示：')
    print('  - 输入科学数据相关的查询（如：查找铝合金7075的屈服强度）')
    print('  - 输入 "quit" 或 "exit" 退出')
    print('  - 输入 "example" 查看示例查询')
    print()
    print('=' * 70)
    print()

    # 编译子图
    print('正在初始化意图澄清子图...')
    try:
        graph = compile_intent_clarification_graph()
        print('✓ 子图初始化成功！')
        print()
    except Exception as e:
        print(f'✗ 初始化失败: {e}')
        return

    # 交互循环
    while True:
        print('-' * 70)
        user_input = input('请输入您的查询 > ').strip()
        print()

        if not user_input:
            print('⚠ 请输入查询内容')
            continue

        if user_input.lower() in ['quit', 'exit', 'q']:
            print('感谢使用！再见！')
            break

        if user_input.lower() == 'example':
            print('示例查询：')
            print('  1. 查找铝合金7075的屈服强度数据')
            print('  2. 帮我找超新星的光变曲线')
            print('  3. 查询钛合金的高温拉伸性能')
            print('  4. 找2020年后发表的关于石墨烯的研究')
            print()
            continue

        # 执行意图澄清
        print('正在分析您的查询...')
        print()

        try:
            result = graph.invoke({
                'original_query': user_input,
                'query_context': {'domain': 'general'},
                '_auto_confirm': True
            })

            # 显示结果
            print('=' * 70)
            print('意图澄清结果')
            print('=' * 70)
            print()

            extracted_params = result.get('extracted_parameters', {})
            clarified_intent = result.get('clarified_intent', {})

            print(f'原始查询: {user_input}')
            print()

            print('提取的参数:')
            print(f'  实体 (entities):')
            entities = clarified_intent.get('entities', [])
            if entities:
                for entity in entities:
                    print(f'    - {entity}')
            else:
                print('    (未识别)')
            print()

            print(f'  属性 (properties):')
            properties = clarified_intent.get('properties', [])
            if properties:
                for prop in properties:
                    print(f'    - {prop}')
            else:
                print('    (未识别)')
            print()

            print(f'  条件 (conditions):')
            conditions = clarified_intent.get('conditions', {})
            if conditions:
                for key, value in conditions.items():
                    print(f'    - {key}: {value}')
            else:
                print('    (无)')
            print()

            compromise_flag = result.get('compromise_flag', False)
            if compromise_flag:
                print('⚠ 注意: 部分参数为AI推测')

            clarification_turns = result.get('_clarification_turns', 0)
            print(f'追问轮次: {clarification_turns}')
            print()

            # 显示JSON格式（方便复制）
            print('JSON格式:')
            print(json.dumps(clarified_intent, ensure_ascii=False, indent=2))
            print()

        except Exception as e:
            print('✗ 执行失败')
            print(f'错误: {type(e).__name__}')
            print(f'详情: {e}')
            print()

            import traceback
            print('详细错误信息:')
            traceback.print_exc()
            print()


if __name__ == '__main__':
    try:
        interactive_test_intent()
    except KeyboardInterrupt:
        print('\n\n用户中断，退出程序。')
    except Exception as e:
        print(f'\n程序异常: {e}')
        import traceback
        traceback.print_exc()
