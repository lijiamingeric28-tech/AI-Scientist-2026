"""
集成测试 - 阶段2：20篇PDF完整测试

测试流程：
1. Mock意图澄清输出（FRB + dispersion_measure）
2. 检索子图：限制20篇（per_page=20），无引用扩展
3. 提取子图：处理所有下载成功的PDF
"""

import sys
import os
from pathlib import Path
import logging
from datetime import datetime

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 设置环境变量
os.environ['OPENAI_API_KEY'] = 'sk-ws-H.EDIIHIY.9cun.MEUCIE8kl0mOSYBF9LRUMCtGJAop8bFeWLPoYzODMZqZbGZlAiEA2HGXz7Z8sMfsmgzv0Kt0BgKPNoTfeDabpFEtH4X1Yj4'
os.environ['OPENAI_BASE_URL'] = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

from models.clarified_intent import ClarifiedIntent
from state.retrieval_state import RetrievalState
from pipeline.retrieval.agents import expand_query_agent, paper_search_agent, filter_rank_agent, download_agent_sync
from pipeline.extraction.graph import create_extraction_graph


def setup_logger():
    """设置日志"""
    log_dir = Path(__file__).parent / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = log_dir / f'integration_20pdfs_{timestamp}.log'
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger, log_file


def main():
    print('=' * 80)
    print('集成测试 - 阶段2：20篇PDF完整测试')
    print('=' * 80)
    
    logger, log_file = setup_logger()
    logger.info('Integration test (20 PDFs) started')
    logger.info(f'Log file: {log_file}')
    
    # Step 1: Mock意图澄清输出
    logger.info('=' * 80)
    logger.info('[Step 1] Creating mock intent')
    intent_params = ClarifiedIntent(
        entities=['FRB', 'fast radio burst'],
        properties=['dispersion_measure', 'DM'],
        conditions={}
    )
    logger.info(f'Intent: entities={intent_params.entities}, properties={intent_params.properties}')
    
    # Step 2: 手动运行检索Agents（控制per_page=20）
    logger.info('=' * 80)
    logger.info('[Step 2] Running retrieval agents manually (per_page=20)')
    
    state: RetrievalState = {
        'intent_params': intent_params
    }
    
    try:
        # Agent A: expand_query
        logger.info('[Agent A] Expanding query...')
        state = expand_query_agent(state)
        
        # Agent B: paper_search（修改per_page为20）
        logger.info('[Agent B] Searching papers (per_page=20)...')
        expanded_queries = state.get("expanded_queries")
        if not expanded_queries or "openalex" not in expanded_queries:
            logger.error("expanded_queries missing")
            return 1
        
        search = expanded_queries["openalex"]["search"]
        filter_dict = expanded_queries["openalex"]["filter"]
        per_page = 20  # 强制设置为20
        
        from tools.paper_search import call_openalex_api
        papers = call_openalex_api(search, filter_dict, per_page)
        state["papers"] = papers
        state["pubmed_papers"] = []  # 跳过PubMed
        state["citation_papers"] = []  # 跳过引用扩展
        
        logger.info(f'Retrieved {len(papers)} papers from OpenAlex')
        
        # Agent E: filter_rank
        logger.info('[Agent E] Filtering and ranking...')
        state = filter_rank_agent(state)
        
        # Agent C: download
        logger.info('[Agent C] Downloading papers...')
        state = download_agent_sync(state)
        
        filtered_papers = state.get('filtered_papers', [])
        logger.info(f'Retrieval completed: {len(filtered_papers)} papers')
        
        if filtered_papers:
            logger.info(f'Preview (first 3):')
            for i, paper in enumerate(filtered_papers[:3], 1):
                logger.info(f'  [{i}] {paper.title[:60]}...')
                logger.info(f'      Download: {paper.download_status}')
        
    except Exception as e:
        logger.error(f'Retrieval failed: {e}', exc_info=True)
        return 1
    
    # Step 3: 过滤下载成功的papers
    logger.info('=' * 80)
    logger.info('[Step 3] Filtering successfully downloaded papers')
    
    valid_papers = [
        p for p in filtered_papers
        if p.download_status == "success" and p.local_path
    ]
    
    logger.info(f'Valid papers: {len(valid_papers)}/{len(filtered_papers)}')
    
    if not valid_papers:
        logger.warning('No valid papers for extraction')
        return 1
    
    # Step 4: 运行提取子图
    logger.info('=' * 80)
    logger.info('[Step 4] Running extraction subgraph')
    logger.info(f'Processing {len(valid_papers)} PDFs...')
    
    extraction_graph = create_extraction_graph()
    
    extraction_input = {
        'intent_params': intent_params,
        'filtered_papers': valid_papers
    }
    
    try:
        extraction_output = extraction_graph.invoke(extraction_input)
        
        grounded_data = extraction_output['grounded_data']
        verification_rate = extraction_output['verification_rate']
        
        logger.info('=' * 80)
        logger.info('Extraction completed!')
        logger.info(f"  - Sources: {len(grounded_data['sources'])}")
        logger.info(f"  - Records: {len(grounded_data['records'])}")
        logger.info(f"  - Verification rate: {verification_rate*100:.1f}%")
        
        # 统计
        vlm_stats = extraction_output.get('vlm_stats', {})
        ocr_stats = extraction_output.get('ocr_stats', {})
        logger.info('VLM Stats:')
        logger.info(f"  - Success PDFs: {vlm_stats.get('success_pdfs', 0)}")
        logger.info(f"  - Total observations: {vlm_stats.get('total_observations', 0)}")
        logger.info('OCR Stats:')
        logger.info(f"  - Success pages: {ocr_stats.get('success_pages', 0)}/{ocr_stats.get('total_pages', 0)}")
        
        # 显示样例
        if grounded_data['records']:
            logger.info('Sample records (first 5):')
            for i, record in enumerate(grounded_data['records'][:5], 1):
                logger.info(f"  [{i}] {record['entity_name']}: {record['property_value']} {record['property_unit']}")
        
        # 保存结果
        output_dir = Path(__file__).parent / 'output'
        output_dir.mkdir(parents=True, exist_ok=True)
        
        import json
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f'integration_20pdfs_{timestamp}.json'
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(grounded_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f'Output saved to: {output_file}')
        logger.info('=' * 80)
        logger.info('Integration test (20 PDFs) PASSED!')
        logger.info('=' * 80)
        
        return 0
        
    except Exception as e:
        logger.error(f'Extraction failed: {e}', exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
