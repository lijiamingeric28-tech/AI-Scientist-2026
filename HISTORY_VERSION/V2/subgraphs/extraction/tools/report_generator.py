"""
报告生成工具
"""

import json
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def generate_extraction_report(state: dict) -> str:
    """
    生成详细的Markdown+JSON报告

    Args:
        state: ExtractionState字典

    Returns:
        Markdown报告文件路径
    """
    from config.constants import REPORT_DIR

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = Path(REPORT_DIR)
    report_dir.mkdir(parents=True, exist_ok=True)

    # 1. 生成JSON报告
    json_path = report_dir / f"extraction_result_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "grounded_data": state["grounded_data"],
            "vlm_stats": state["vlm_stats"],
            "ocr_stats": state["ocr_stats"],
            "verification_rate": state["verification_rate"]
        }, f, indent=2, ensure_ascii=False)

    logger.info(f"JSON报告已保存: {json_path}")

    # 2. 生成Markdown报告
    md_path = report_dir / f"extraction_report_{timestamp}.md"

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# 提取子图执行报告\n\n")
        f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Schema版本**: 1.1.0\n\n")
        f.write(f"---\n\n")

        # VLM统计
        vlm = state["vlm_stats"]
        f.write(f"## 📊 VLM提取统计\n\n")
        f.write(f"- **总PDF数**: {vlm['total_pdfs']}\n")
        f.write(f"- **成功PDF**: {vlm['success_pdfs']}\n")
        f.write(f"- **失败PDF**: {vlm['failed_pdfs']}\n")
        f.write(f"- **总提取记录数**: {vlm['total_observations']}\n\n")

        # OCR统计
        ocr = state["ocr_stats"]
        f.write(f"## 📝 OCR提取统计\n\n")
        f.write(f"- **总页数**: {ocr['total_pages']}\n")
        f.write(f"- **成功页数**: {ocr['success_pages']}\n")
        f.write(f"- **失败页数**: {ocr['failed_pages']}\n\n")

        # 验证统计
        verified = len(state["verified_records"])
        failed = len(state["failed_records"])
        total = verified + failed
        f.write(f"## ✅ 忠实度验证统计\n\n")
        f.write(f"- **总记录数**: {total}\n")
        f.write(f"- **验证通过**: {verified}\n")
        f.write(f"- **验证失败**: {failed}\n")
        f.write(f"- **验证通过率**: {state['verification_rate']*100:.1f}%\n\n")

        # grounded_data统计
        gd = state["grounded_data"]
        f.write(f"## 📦 最终输出统计\n\n")
        f.write(f"- **源文献数**: {len(gd['sources'])}\n")
        f.write(f"- **最终记录数**: {len(gd['records'])}\n\n")

        f.write(f"---\n\n")
        f.write(f"**JSON结果**: `{json_path.name}`\n")

    logger.info(f"Markdown报告已保存: {md_path}")

    return str(md_path)
