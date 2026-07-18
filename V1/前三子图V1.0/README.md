# 科学数据提取流水线 (Scientific Data Extraction Pipeline)

一个基于 LangGraph 的综合性端到端科学文献数据提取系统，支持意图澄清、文献检索、数据提取和验证。

## 主要特性

- **智能意图澄清**：基于大语言模型（LLM）的自然语言理解
- **双源检索**：集成 OpenAlex 和 PubMed
- **高性能下载**：基于 Unpaywall 批量查询的多线程并发下载
- **VLM 数据提取**：使用视觉语言模型（VLM）进行高精度数据提取
- **OCR 验证**：支持按需 OCR 验证与双重阈值保真度检查
- **标准化输出**：采用包含完整溯源信息的 `grounded_data V1.1` 格式

## 性能指标

基于 20 篇论文的测试结果：

| 指标             | 结果           |
| ---------------- | -------------- |
| VLM 提取成功率   | 100%           |
| 下载成功率       | 95%            |
| 保真度验证通过率 | 90.7%          |
| 平均处理速度     | 20秒/PDF (VLM) |
| OCR 处理速度     | 4.7秒/页       |

## 快速开始

### 1. 安装

```bash
git clone https://github.com/yourusername/scientific-data-extraction-pipeline.git
cd scientific-data-extraction-pipeline
pip install -r requirements.txt
```

### 2. 配置

```bash
cp .env.example .env
# 在 .env 文件中填入您的 API 密钥
```

必填配置：

```bash
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

### 3. 运行测试

```bash
python tests/test_full_pipeline.py
```

## 使用方法

### 完整流水线

```python
from pipeline.main_graph import create_main_graph
from models.clarified_intent import ClarifiedIntent

# 创建主图
main_graph = create_main_graph()

# 提供澄清后的意图
state = {
    'intent_params': ClarifiedIntent(
        entities=['FRB', 'fast radio burst'],
        properties=['dispersion_measure', 'DM'],
        conditions={}
    )
}

# 执行流水线
result = main_graph.invoke(state)

# 获取结果
grounded_data = result['grounded_data']
print(f"提取了 {len(grounded_data['records'])} 条记录")
```

### 仅检索

```python
from pipeline.retrieval.graph import create_retrieval_graph

retrieval_graph = create_retrieval_graph(enable_citation_expansion=False)
result = retrieval_graph.invoke(state)
filtered_papers = result['filtered_papers']
```

### 仅提取

```python
from pipeline.extraction.graph import create_extraction_graph

extraction_graph = create_extraction_graph()
result = extraction_graph.invoke(state)
grounded_data = result['grounded_data']
```

## 配置说明

### 核心配置文件

#### configs/constants.py - 系统常量

关键配置选项：

```python
# 模型配置
INTENT_MODEL = "qwen-plus"           # 意图澄清模型
VLM_MODEL = "qwen3.7-plus"           # VLM 提取模型
OCR_MODEL = "qwen3.5-ocr"            # OCR 模型

# 并发配置
VLM_CONCURRENCY = 20                 # VLM 并发线程数
OCR_CONCURRENCY = 20                 # OCR 并发线程数
DOWNLOAD_CONCURRENCY = 5             # 下载并发线程数

# 验证配置
ENTITY_THRESHOLD = 90                # 实体验证阈值
PROPERTY_THRESHOLD = 95              # 属性验证阈值

# 检索配置
ENABLE_PUBMED = False                # 是否启用 PubMed 检索
OPENALEX_PER_PAGE = 50               # 每页结果数
MAX_PAPERS = 100                     # 最大结果数
CITATION_DEPTH = 1                   # 引文扩展深度
```

#### configs/openalex_config.py - OpenAlex 配置

```python
# 默认过滤器
DEFAULT_FILTERS = {
    "publication_year": "2015-2025",  # 出版年份范围
    "cited_by_count": ">5",           # 最低引用量
    "is_oa": None,                    # 开放获取状态
}

# 领域/主题系统
TOPICS_CONFIG = {
    "use_topics": True,               # 使用主题 (Topics) 过滤
    "fallback_to_concepts": True,     # 降级使用概念 (Concepts) 过滤
}
```

#### configs/prompts_extraction.py - 提取提示词

可自定义 VLM 提取提示词和 schema，以进行特定领域的优化。

### 环境变量

在 `.env` 文件中配置：

```bash
# 必填
OPENAI_API_KEY=sk-xxxxx
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# OpenAlex（可选但推荐）
OPENALEX_EMAIL=your-email@example.com    # 用于加入礼貌池（Polite Pool）
OPENALEX_API_KEY=your-key                # 用于获取更高的速率限制

# PubMed（可选）
ENABLE_PUBMED=false
PUBMED_API_KEY=your-key
PUBMED_EMAIL=your-email@example.com
```

## 项目结构

```text
scientific-data-extraction-pipeline/
├── configs/                # 配置文件
│   ├── constants.py        # 系统常量
│   ├── openalex_config.py  # OpenAlex 配置
│   └── prompts*.py         # 提示词模板
├── models/                 # 数据模型
│   ├── clarified_intent.py
│   ├── paper_metadata.py
│   └── grounded_data.py
├── state/                  # 状态定义
│   ├── main_state.py
│   ├── intent_clarification_state.py
│   ├── retrieval_state.py
│   └── extraction_state.py
├── pipeline/               # 流水线定义
│   ├── main_graph.py
│   ├── intent/             # 意图澄清子图
│   ├── retrieval/          # 检索子图
│   └── extraction/         # 提取子图
├── tools/                  # 工具函数
│   ├── paper_search/
│   ├── download/
│   └── extraction/
├── tests/                  # 测试用例
│   └── test_full_pipeline.py
└── data/                   # 数据目录
    ├── papers/
    ├── logs/
    └── reports/
```

## 常见问题 (FAQ)

### API 调用失败

请检查 `.env` 文件中的 API 密钥和 Base URL 设置。

### 验证通过率低

可在 `configs/constants.py` 中调低验证阈值：

```python
ENTITY_THRESHOLD = 85
PROPERTY_THRESHOLD = 90
```

### 内存溢出 (OOM)

降低并发数：

```python
VLM_CONCURRENCY = 10
OCR_CONCURRENCY = 10
DOWNLOAD_CONCURRENCY = 3
```

### 下载失败率高

设置 OpenAlex 邮箱以加入礼貌池（Polite Pool）：

```bash
OPENALEX_EMAIL=your-email@example.com
```

### 禁用引文扩展

```python
retrieval_graph = create_retrieval_graph(enable_citation_expansion=False)
```

## 高级配置

### 自定义 VLM 提示词

编辑 `configs/prompts_extraction.py`：

```python
def generate_vlm_prompt(entity_type: str, property_name: str) -> str:
    if entity_type == "alloy":
        return "Materials science extraction prompt..."  # 材料科学提取提示词...
    return f"Standard prompt for {entity_type}..."       # 针对 {entity_type} 的标准提示词...
```

### 自定义验证逻辑

编辑 `tools/extraction/verification.py` 中的 `verify_field()` 函数。

### 添加新数据源

1. 创建 `pipeline/retrieval/agents/your_source_search.py`
2. 在 `pipeline/retrieval/graph.py` 中添加新节点
3. 更新 `models/paper_metadata.py`

## 输出格式

### grounded_data V1.1 格式

```json
{
  "schema_version": "1.1.0",
  "sources": [
    {
      "source_id": "W3010745702",
      "source_type": "paper",
      "doi": "10.1038/...",
      "title": "Paper Title",
      "authors": ["Author1", "Author2"],
      "year": 2020,
      "journal": "Nature",
      "access_path": "/path/to/paper.pdf",
      "retrieval_priority": 0.95
    }
  ],
  "records": [
    {
      "record_id": "W3010745702_FRB_121102_dispersion_measure_0",
      "source_id": "W3010745702",
      "entity_type": "fast_radio_burst",
      "entity_name": "FRB 121102",
      "property_name": "dispersion_measure",
      "property_value": 560.5,
      "property_unit": "pc cm^-3",
      "trace_id": "doc0_p5",
      "provenance": {
        "page": 5,
        "bbox": [150, 320, 210, 335]
      },
      "extraction_method": "vlm_text"
    }
  ]
}
```

## 系统架构

### 意图澄清子图

- Agent A: Evaluate_Intent - 评估意图完整性
- Agent B: Ask_User_Guided - 引导式用户交互
- Agent C: Confirm_Intent - 确认并标准化

### 检索子图

- Agent A: Expand_Query - 查询词扩展
- Agent B: Paper_Search - OpenAlex 检索
- Agent B2: PubMed_Search - PubMed 检索（可选）
- Agent D: Citation_Expansion - 引文链扩展（可选）
- Agent E: Filter_Rank - 过滤与排序
- Agent C: Download - 并发下载

### 提取子图

- Agent 1: Prepare_and_Prompt - 准备与提示词生成
- Agent 2: VLM_Extract - VLM 批量提取
- Agent 3: OCR_Extract - 按需 OCR 提取
- Agent 4: Fidelity_Validation - 保真度验证
- Agent 5: Format_Output - 格式化输出

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

MIT 许可证 - 详见 LICENSE 文件

## 更新日志

### V2.1 (2026-07-18)

- 完成三大子图架构（意图 + 检索 + 提取）
- 双源检索（OpenAlex + PubMed）
- 按需 OCR 触发机制
- 双重阈值验证策略
- grounded_data V1.1 标准格式
- 通过端到端测试（90.7% 验证通过率）

---

如果这个项目对您有帮助，请给个 Star！⭐
