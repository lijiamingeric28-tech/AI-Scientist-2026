"""
提取子图测试脚本

测试配置:
- Entity: FRB (快速射电暴)
- Property: dispersion_measure (色散量)
- Papers: TOP 10 PDFs (预期230条记录)
"""

import sys
import os
from pathlib import Path
import logging
from datetime import datetime
import json

# 添加项目根目录到path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 加载环境变量
from dotenv import load_dotenv
load_dotenv(project_root / '.env')

from extraction_subgraph import create_extraction_graph
from models import ClarifiedIntent


# TOP 10 PDFs (按记录数排序)
TOP10_PDFS = [
    'W3010745702.pdf',  # 46 records
    'W4367056813.pdf',  # 39 records
    'W2885497170.pdf',  # 36 records
    'W2237502728.pdf',  # 34 records
    'W2970847970.pdf',  # 16 records
    'W2908614976.pdf',  # 13 records
    'W2323094335.pdf',  # 12 records
    'W2617164508.pdf',  # 12 records
    'W2909226516.pdf',  # 12 records
    'W1705707652.pdf',  # 10 records
]


def setup_logger():
    """设置日志"""
    log_dir = Path(__file__).parent / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = log_dir / f'test_{timestamp}.log'
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger, log_file


def create_test_papers():
    """创建测试papers数据"""
    papers_dir = Path(__file__).parent / 'test_data' / 'papers'
    papers = []
    
    available_pdfs = {p.name: p for p in papers_dir.glob('*.pdf')}
    
    for pdf_name in TOP10_PDFS:
        paper_id = pdf_name.replace('.pdf', '')
        
        if pdf_name in available_pdfs:
            papers.append({
                'id': paper_id,
                'title': f'Test Paper {paper_id}',
                'doi': None,
                'authors': [],
                'year': 2020,
                'journal': 'Test Journal',
                'local_path': str(available_pdfs[pdf_name].absolute()),
                'download_status': 'success',
                'score': 0.95
            })
        else:
            print(f'Warning: {pdf_name} not found')
    
    print(f'PDFs loaded: {len(papers)}/{len(TOP10_PDFS)}')
    return papers


def main():
    print('=' * 80)
    print('提取子图测试')
    print('测试数据: TOP 10 PDFs (预期230条记录)')
    print('=' * 80)
    
    logger, log_file = setup_logger()
    logger.info('Test started')
    logger.info(f'Log file: {log_file}')
    
    # 检查API密钥
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        logger.error('OPENAI_API_KEY not found in environment')
        print('Error: Please set OPENAI_API_KEY in .env file or environment variable')
        return 1
    
    logger.info(f'API Key configured: {api_key[:10]}...')
    
    # 准备测试数据
    logger.info('Preparing test data...')
    intent_params = ClarifiedIntent(
        entities=['FRB', '快速射电暴'],
        properties=['dispersion_measure', '色散量', 'DM'],
        conditions={}
    )
    filtered_papers = create_test_papers()
    
    if not filtered_papers:
        logger.error('No PDFs found')
        return 1
    
    logger.info(f'Intent: {intent_params}')
    logger.info(f'Papers: {len(filtered_papers)} PDFs ready')
    
    # 创建初始State
    initial_state = {
        'intent_params': intent_params,
        'filtered_papers': filtered_papers
    }
    
    # 创建并执行提取子图
    logger.info('Creating extraction graph...')
    extraction_graph = create_extraction_graph()
    
    logger.info('Starting extraction...')
    logger.info('=' * 80)
    
    try:
        result_state = extraction_graph.invoke(initial_state)
        
        logger.info('=' * 80)
        logger.info('Extraction completed!')
        
        # 输出结果
        grounded_data = result_state['grounded_data']
        logger.info('Results:')
        logger.info(f"  - Schema version: {grounded_data['schema_version']}")
        logger.info(f"  - Sources: {len(grounded_data['sources'])}")
        logger.info(f"  - Records: {len(grounded_data['records'])}")
        logger.info(f"  - Verification rate: {result_state['verification_rate']*100:.1f}%")
        logger.info(f"  - Expected records: 230")
        logger.info(f"  - Recovery rate: {len(grounded_data['records'])/230*100:.1f}%")
        
        # 统计
        vlm_stats = result_state.get('vlm_stats', {})
        ocr_stats = result_state.get('ocr_stats', {})
        logger.info('VLM Stats:')
        logger.info(f"  - Success PDFs: {vlm_stats.get('success_pdfs', 0)}")
        logger.info(f"  - Total observations: {vlm_stats.get('total_observations', 0)}")
        logger.info('OCR Stats:')
        logger.info(f"  - Success pages: {ocr_stats.get('success_pages', 0)}/{ocr_stats.get('total_pages', 0)}")
        
        # 保存结果
        output_dir = Path(__file__).parent / 'output'
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f'grounded_data_{timestamp}.json'
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(grounded_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f'Output saved to: {output_file}')
        
        # 样例
        logger.info('Sample records (first 5):')
        for i, record in enumerate(grounded_data['records'][:5], 1):
            logger.info(f"  [{i}] {record['entity_name']}: {record['property_value']} {record['property_unit']}")
        
        logger.info('=' * 80)
        logger.info('Test completed successfully!')
        logger.info('=' * 80)
        
        return 0
        
    except Exception as e:
        logger.error(f'Extraction failed: {e}', exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
