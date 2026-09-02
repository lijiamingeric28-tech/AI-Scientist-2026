# 提取子图 V2.0

一个基于VLM和OCR的科学文献数据提取系统，支持从PDF中提取结构化数据并进行忠实度验证。

## 特性

- ✅ **5-Agent架构**: 规范化、VLM提取、OCR验证、忠实度验证、格式化输出
- ✅ **高并发处理**: VLM和OCR均支持20线程并发
- ✅ **按需OCR**: 只对VLM提取到数据的页面进行OCR，降低成本60-80%
- ✅ **双阈值验证**: Entity(90)和Property(95)分别验证
- ✅ **grounded_data V1.1**: 标准化输出格式，包含完整溯源信息
- ✅ **详细日志**: 完整的执行日志和统计报告

## 系统架构

```
提取子图 (ExtractionSubgraph)
├── Agent 1: Prepare_and_Prompt (准备与Prompt生成)
│   └── 使用LLM规范化intent参数
├── Agent 2: VLM_Extract (VLM批量提取)
│   └── 20线程并发，自动重试
├── Agent 3: OCR_Extract (OCR按需提取)
│   └── 仅处理VLM有数据的页面
├── Agent 4: Fidelity_Validation (忠实度验证)
│   └── TheFuzz模糊匹配，双阈值策略
└── Agent 5: Format_Output (格式化输出)
    └── grounded_data V1.1 + Markdown报告
```

## 安装

### 1. 环境要求

- Python 3.10+
- 依赖包：见 `requirements.txt`

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置API密钥

编辑 `.env` 文件：

```bash
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

或设置环境变量：

```bash
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

## 快速开始

### 运行示例测试

```bash
cd tests
python test_extraction.py
```

### 测试结果

预期输出：
- VLM提取成功率: 100%
- 忠实度验证率: 80-85%
- 输出: `output/grounded_data_*.json`

## 使用方法

### 独立使用

```python
from extraction_subgraph import create_extraction_graph
from models import ClarifiedIntent

# 创建提取子图
extraction_graph = create_extraction_graph()

# 准备输入
state = {
    'intent_params': ClarifiedIntent(
        entities=['FRB'],
        properties=['dispersion_measure'],
        conditions={}
    ),
    'filtered_papers': [
        {
            'id': 'W3010745702',
            'local_path': '/path/to/paper.pdf',
            'download_status': 'success',
            # ... 其他字段
        }
    ]
}

# 执行提取
result = extraction_graph.invoke(state)

# 获取结果
grounded_data = result['grounded_data']
print(f"提取了 {len(grounded_data['records'])} 条记录")
```

### 作为子图集成

```python
from langgraph.graph import StateGraph
from extraction_subgraph import create_extraction_graph

# 创建主流程
main_graph = StateGraph(MainState)
main_graph.add_node("extraction", create_extraction_subgraph_node())
# ... 添加其他节点
```

## 配置

### 核心配置 (`configs/constants.py`)

```python
# VLM配置
VLM_CONCURRENCY = 20              # 并发线程数
VLM_MODEL = "qwen3.7-plus"        # VLM模型
VLM_MAX_TOKENS = 8192             # 最大输出tokens

# OCR配置
OCR_CONCURRENCY = 20              # 并发线程数
OCR_MODEL = "qwen3.5-ocr"         # OCR模型

# 验证配置
ENTITY_THRESHOLD = 90             # Entity验证阈值
PROPERTY_THRESHOLD = 95           # Property验证阈值
```

### Prompt配置 (`configs/prompts_extraction.py`)

- `NORMALIZATION_PROMPT`: 参数规范化Prompt
- `generate_vlm_prompt()`: VLM提取Prompt生成函数
- `VLM_EXTRACTION_SCHEMA`: Structured Output Schema

## 输出格式

### grounded_data V1.1

```json
{
  "schema_version": "1.1.0",
  "sources": [
    {
      "source_id": "W3010745702",
      "source_type": "paper",
      "title": "...",
      "doi": "...",
      "access_path": "/path/to/paper.pdf"
    }
  ],
  "records": [
    {
      "record_id": "W3010745702_FRB_121102_dispersion_measure_0",
      "source_id": "W3010745702",
      "entity_type": "FRB",
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

## 测试数据

`tests/test_data/papers/` 包含10个TOP高产论文（来自FRB色散量研究）：

| PDF | 预期记录数 |
|-----|-----------|
| W3010745702.pdf | 46条 |
| W4367056813.pdf | 39条 |
| W2885497170.pdf | 36条 |
| ... | ... |

**总计**: 230条记录

## 性能指标

基于TOP 10测试（10个PDF，230条预期记录）：

- **VLM提取成功率**: 100%
- **VLM提取记录数**: 223条 (97%)
- **OCR成功率**: 100%
- **忠实度验证率**: 84.3%
- **最终记录数**: 188条
- **总耗时**: 6分44秒
- **平均处理速度**: 29秒/PDF

## 目录结构

```
extraction_subgraph_v2/
├── README.md
├── requirements.txt
├── .env.example
├── configs/                    # 配置文件
│   ├── constants.py
│   └── prompts_extraction.py
├── models/                     # 数据模型
│   ├── clarified_intent.py
│   └── grounded_data.py
├── state/                      # State定义
│   └── extraction_state.py
├── agents/                     # 5个Agent
│   ├── prepare_and_prompt.py
│   ├── vlm_extract.py
│   ├── ocr_extract.py
│   ├── fidelity_validation.py
│   └── format_output.py
├── tools/                      # 工具函数
│   ├── pdf_processing.py
│   ├── vlm_client.py
│   ├── ocr_client.py
│   ├── verification.py
│   └── report_generator.py
├── extraction_subgraph.py      # 主入口
├── tests/                      # 测试
│   ├── test_extraction.py
│   └── test_data/
│       └── papers/            # 测试PDF
└── docs/                       # 文档
    ├── DESIGN.md
    └── API.md
```

## 常见问题

### Q: API调用失败
A: 检查API密钥和网络连接。确保 `.env` 配置正确。

### Q: 验证率过低
A: 可以降低验证阈值：
```python
ENTITY_THRESHOLD = 85    # 从90降到85
PROPERTY_THRESHOLD = 90  # 从95降到90
```

### Q: 内存不足
A: 减少并发数：
```python
VLM_CONCURRENCY = 10  # 从20降到10
OCR_CONCURRENCY = 10
```

### Q: VLM返回空结果
A: 检查PDF质量和Prompt是否匹配目标数据类型。

## 许可证

MIT License

## 作者

Claude + Eric

## 更新日志

### V2.0 (2026-07-18)
- ✅ 完整的5-Agent架构
- ✅ 按需OCR触发
- ✅ 双阈值验证策略
- ✅ grounded_data V1.1格式
- ✅ 详细日志系统
- ✅ 独立运行支持

---

**Star ⭐ 如果这个项目对你有帮助！**
