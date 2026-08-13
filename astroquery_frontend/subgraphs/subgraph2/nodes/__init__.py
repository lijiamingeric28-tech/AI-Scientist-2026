"""节点模块初始化

L-05: simbad_resolver 为 B2 收敛后的死代码（图已移除该节点），不再导出——
文件 simbad_resolver.py 保留留档，但不再连带 import astroquery.simbad，
避免依赖缺失时整个 nodes 包导入即崩。
"""

from .database_query import database_query
from .ads_search import ads_search, build_ads_query
from .unpaywall_query import unpaywall_query
from .pdf_download import pdf_download
from .supplementary_query import supplementary_query
from .result_aggregator import result_aggregator

__all__ = [
    'database_query',
    'ads_search',
    'build_ads_query',
    'unpaywall_query',
    'pdf_download',
    'supplementary_query',
    'result_aggregator',
]
