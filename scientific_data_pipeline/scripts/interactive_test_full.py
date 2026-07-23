"""
意图澄清子图 - 完整交互式测试（包含确认步骤）

完整流程：
1. 用户输入查询
2. Agent A 评估意图并提取参数
3. Agent B 追问（如需要）
4. Agent C 展示确认表单，等待用户确认/修改/拒绝
5. 输出最终结果
"""

import sys
sys.path.insert(0, '.')

from dotenv import load_dotenv
load_dotenv()

from subgraphs.intent_clarification.graph import compile_intent_clarification_graph
import json


def interactive_test_with_confirmation():
    """完整交互式测试（包含确认步骤）"""

    print('=' * 70)
    print(' ' * 10 + '意图澄清子图 - 完整交互式测试')
    print('=' * 70)
    print()
    print('这是完整的交互式测试，包含所有确认步骤。')
    print()
    print('完整流程：')
    print('  1. 您输入查询')
    print('  2. AI提取参数')
    print('  3. AI可能追问缺失信息')
    print('  4. 您确认最终参数（确认/修改/拒绝）')
    print('  5. 输出最终结果')
    print()
    print('提示：')
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

        # 执行意图澄清（完整交互模式）
        print('正在分析您的查询...')
        print()

        try:
            # 注意：这里 _auto_confirm=False 或者不设置，启用完整交互
            result = graph.invoke({
                'original_query': user_input,
                'query_context': {'domain': 'general'},
                # 不设置 _auto_confirm，让用户完整体验交互流程
            })

            # 显示结果
            print()
            print('=' * 70)
            print('意图澄清完成！')
            print('=' * 70)
            print()

            clarified_intent = result.get('clarified_intent', {})
            user_confirmed = result.get('user_confirmed', False)
            compromise_flag = result.get('compromise_flag', False)
            clarification_turns = result.get('_clarification_turns', 0)

            print('最终结果:')
            print(f'  原始查询: {user_input}')
            print()

            print('  提取的实体 (entities):')
            entities = clarified_intent.get('entities', [])
            if entities:
                for entity in entities:
                    print(f'    - {entity}')
            else:
                print('    (未识别)')
            print()

            print('  提取的属性 (properties):')
            properties = clarified_intent.get('properties', [])
            if properties:
                for prop in properties:
                    print(f'    - {prop}')
            else:
                print('    (未识别)')
            print()

            print('  提取的条件 (conditions):')
            conditions = clarified_intent.get('conditions', {})
            if conditions:
                for key, value in conditions.items():
                    print(f'    - {key}: {value}')
            else:
                print('    (无)')
            print()

            print('  状态信息:')
            print(f'    - 用户确认: {"是" if user_confirmed else "否"}')
            print(f'    - AI推测: {"是" if compromise_flag else "否"}')
            print(f'    - 追问轮次: {clarification_turns}')
            print()

            # 显示JSON格式
            print('  JSON格式:')
            print('  ' + json.dumps(clarified_intent, ensure_ascii=False, indent=2).replace('\n', '\n  '))
            print()

            if not user_confirmed:
                print('⚠ 注意: 用户拒绝了查询，未生成有效的意图参数')
                print()

        except KeyboardInterrupt:
            print()
            print('⚠ 用户中断了当前查询')
            print()
            continue

        except Exception as e:
            print()
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
        interactive_test_with_confirmation()
    except KeyboardInterrupt:
        print('\n\n用户中断，退出程序。')
    except Exception as e:
        print(f'\n程序异常: {e}')
        import traceback
        traceback.print_exc()
