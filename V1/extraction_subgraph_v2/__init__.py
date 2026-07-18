"""
提取子图 V2.0

一个基于VLM和OCR的科学文献数据提取系统
"""

__version__ = "2.0.0"
__author__ = "Claude + Eric"

from .extraction_subgraph import create_extraction_graph

__all__ = ['create_extraction_graph']
