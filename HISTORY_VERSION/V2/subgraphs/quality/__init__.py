"""
subgraphs/quality — Quality Control Subgraph (SubGraph 4)

数据清洗与质检子图, 包含 4 个 SubGraph:
  - Assessment: 数据质量评估与路由决策
  - Normalization: 数据标准化清洗
  - Conflict Resolution: 跨来源数据冲突裁决
  - Export: 结构化数据导出

入口:
  from subgraphs.quality.graph import compile_quality_graph
  graph = compile_quality_graph()
"""
