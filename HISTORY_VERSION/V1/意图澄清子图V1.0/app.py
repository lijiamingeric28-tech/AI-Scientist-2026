"""
意图澄清子图 - 主入口（交互式）
"""
from pipeline.intent.graph import create_intent_clarification_graph
from utils.logger import setup_logger
import logging


def main():
    """主函数：运行意图澄清子图"""

    # 配置日志（只保存到文件，不在终端显示）
    from pathlib import Path
    import logging

    log_file = Path("test_logs.log")

    # 配置根日志记录器
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8')  # 只保存到文件
        ],
        force=True  # 强制覆盖已有配置
    )

    # 禁用所有logger的终端输出
    logging.getLogger().handlers = [h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)]

    print(f"✓ 日志已启用，保存到: {log_file.absolute()}")

    print("="*60)
    print("意图澄清子图")
    print("="*60)

    # 获取用户查询
    print("\n请输入您的查询（或按回车使用示例查询）:")
    user_input = input(">>> ")

    if not user_input.strip():
        query = "帮我找铝合金7075在200-400°C下的屈服强度数据"
        print(f"使用示例查询: {query}")
    else:
        query = user_input.strip()

    print("\n正在处理...")

    # 创建Graph
    intent_graph = create_intent_clarification_graph()

    # 初始化State
    initial_state = {
        "original_query": query
    }

    try:
        # 执行Graph（会自动处理追问和确认）
        result = intent_graph.invoke(initial_state)

        # 显示最终结果
        print("\n" + "="*60)
        print("执行完成！")
        print("="*60)

        user_confirmed = result.get('user_confirmed', False)
        compromise_flag = result.get('compromise_flag', False)
        extracted = result.get('extracted_parameters', {})

        print(f"\n用户确认: {'是' if user_confirmed else '否'}")

        if compromise_flag:
            print("⚠️  包含AI推测的参数")

        print(f"\n提取的参数:")

        entities = extracted.get('entities', [])
        if entities:
            print(f"  目标实体: {', '.join(entities) if isinstance(entities, list) else entities}")

        properties = extracted.get('properties', [])
        if properties:
            print(f"  目标属性: {', '.join(properties) if isinstance(properties, list) else properties}")

        conditions = extracted.get('conditions', {})
        if conditions:
            print(f"  约束条件:")
            for key, value in conditions.items():
                print(f"    - {key}: {value}")

        print("="*60)

        if user_confirmed:
            print("\n✓ 意图澄清完成，可以进入下一步（文献检索）")
        else:
            print("\n✗ 用户取消了查询")

    except KeyboardInterrupt:
        print("\n\n用户中断执行")
    except Exception as e:
        print(f"\n执行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
