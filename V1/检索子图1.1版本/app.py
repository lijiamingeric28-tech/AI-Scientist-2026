"""
科学文献数据提取管道 - 主程序入口

完整流程：
1. 意图澄清子图 - 解析用户自然语言查询（完整版）
2. 文献检索子图 - 检索、扩展、下载论文
3. (未来) 数据提取子图 - 提取文献中的数据
4. (未来) 数据清洗子图 - 清洗和导出数据
"""

import sys
import os
import logging
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.logger import setup_logger
from models.clarified_intent import ClarifiedIntent
from state.main_state import MainState
from pipeline.main_graph import create_main_graph


def main():
    """主函数"""
    # 设置日志
    logger = setup_logger(
        name="main",
        level=logging.INFO,
        log_file="./data/logs/main.log"
    )

    logger.info("=" * 80)
    logger.info("科学文献数据提取管道 V1.0 启动")
    logger.info("=" * 80)

    # 用户输入（自然语言查询）
    user_query = input("\n请输入您的查询（例如：Ti-6Al-4V在高温下的抗拉强度）：\n> ")

    if not user_query.strip():
        logger.error("查询不能为空")
        return 1

    logger.info(f"\n用户查询: {user_query}")

    # 初始化主State
    initial_state: MainState = {
        "user_query": user_query,
        # 其他字段将由各子图填充
    }

    # 创建主Graph
    logger.info("\n创建主流程图...")
    main_graph = create_main_graph()

    # 执行完整流程
    logger.info("\n开始执行完整流程...")
    logger.info("-" * 80)

    try:
        final_state = main_graph.invoke(initial_state)

        # 输出结果
        logger.info("-" * 80)
        logger.info("\n✅ 执行完成！")
        logger.info("=" * 80)

        # 显示意图澄清结果
        intent_params = final_state.get("intent_params")
        if intent_params:
            logger.info("\n【意图澄清结果】")
            logger.info(f"  实体: {intent_params.entities}")
            logger.info(f"  属性: {intent_params.properties}")
            logger.info(f"  条件: {intent_params.conditions}")

        # 显示检索结果
        filtered_papers = final_state.get("filtered_papers", [])
        logger.info(f"\n【文献检索结果】获取到 {len(filtered_papers)} 篇论文")

        # 显示下载统计
        success_papers = [p for p in filtered_papers if p.download_status == "success"]
        skipped_papers = [p for p in filtered_papers if p.download_status == "skipped"]
        failed_papers = [p for p in filtered_papers if p.download_status == "failed"]

        logger.info(f"  下载成功: {len(success_papers)} 篇")
        logger.info(f"  已存在: {len(skipped_papers)} 篇")
        logger.info(f"  下载失败: {len(failed_papers)} 篇")

        # 显示前3篇论文
        if success_papers:
            logger.info("\n【前3篇论文】")
            for idx, paper in enumerate(success_papers[:3], 1):
                logger.info(f"\n  [{idx}] {paper.title}")
                logger.info(f"      ID: {paper.id}")
                logger.info(f"      年份: {paper.year}")
                logger.info(f"      引用数: {paper.citation_count}")
                logger.info(f"      分数: {paper.score:.2f}")
                logger.info(f"      本地路径: {paper.local_path}")

        logger.info("\n" + "=" * 80)
        logger.info("程序结束")
        logger.info("=" * 80)

        return 0

    except KeyboardInterrupt:
        logger.warning("\n\n用户中断执行")
        return 130

    except Exception as e:
        logger.error(f"\n执行失败: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
