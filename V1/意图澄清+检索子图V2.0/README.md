# 科学文献检索系统 V2.0

基于LangGraph的智能科学文献检索和下载系统，支持意图澄清、多源检索、引用扩展和智能下载。

---

## 📋 目录

- [功能特性](#功能特性)
- [系统架构](#系统架构)
- [安装配置](#安装配置)
- [使用指南](#使用指南)
- [核心功能](#核心功能)
- [API文档](#api文档)
- [性能数据](#性能数据)
- [故障排除](#故障排除)
- [开发指南](#开发指南)

---

## ✨ 功能特性

### 核心功能

- **智能意图澄清** - 自动识别用户查询意图，通过多轮对话补全缺失信息
- **多源论文检索** - 同时检索OpenAlex和PubMed两大数据库
- **引用网络扩展** - 基于高质量种子论文扩展引用网络
- **智能去重排序** - 多维度评分系统，自动去重和排序
- **多源智能下载** - Waterfall策略，支持Unpaywall多源、Nature专用scraper

### V2.0 新特性

- ✅ **PubMed集成** - 完整的PubMed检索和下载支持
- ✅ **Unpaywall多源策略** - 不只best源，支持多达10+个备用源
- ✅ **Nature专用下载器** - 自动检测nature.com域名并使用专用scraper
- ✅ **下载成功率提升60%** - 从23.4%提升到37.4%

---

## 🏗️ 系统架构

### 整体流程

```
用户输入 
  ↓
意图澄清子图 (Intent Clarification)
  ↓
检索子图 (Retrieval)
  ├─ Agent A: 查询扩展
  ├─ Agent B1: OpenAlex检索
  ├─ Agent B2: PubMed检索
  ├─ Agent D: 引用扩展
  ├─ Agent E: 过滤排序
  └─ Agent C: 智能下载
  ↓
结果输出
```

### 核心模块

```
意图澄清+检索子图V2.0/
├── pipeline/
│   ├── clarification/          # 意图澄清子图
│   │   ├── clarification_graph.py
│   │   └── nodes/              # 各个节点
│   └── retrieval/              # 检索子图
│       └── agents/             # 各个Agent
│           ├── expand_query.py
│           ├── paper_search.py
│           ├── pubmed_search.py
│           ├── citation_expansion.py
│           ├── filter_rank.py
│           └── download.py
├── tools/
│   ├── openalex/               # OpenAlex工具
│   ├── pubmed/                 # PubMed工具
│   └── download/               # 下载工具
│       ├── get_unpaywall_url.py
│       ├── download_with_waterfall.py
│       ├── nature_scraper.py
│       └── pubmed_downloader.py
├── models/                     # 数据模型
├── configs/                    # 配置文件
└── state/                      # 状态管理
```

---

## 🚀 安装配置

### 环境要求

- Python 3.9+
- pip / conda

### 安装步骤

1. **克隆项目**
   ```bash
   cd 意图澄清+检索子图V2.0
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

3. **配置API密钥**
   
   创建 `.env` 文件或设置环境变量：
   ```bash
   # OpenAlex
   export OPENALEX_EMAIL="your-email@example.com"
   
   # PubMed
   export PUBMED_EMAIL="your-email@example.com"
   
   # Unpaywall
   export UNPAYWALL_EMAIL="your-email@example.com"
   
   # LLM API（根据使用的模型）
   export OPENAI_API_KEY="your-key"
   # 或
   export QWEN_API_KEY="your-key"
   ```

4. **验证安装**
   ```bash
   python -c "import langgraph; print('LangGraph installed')"
   python -c "from tools.openalex.search_papers import search_papers; print('Tools ready')"
   ```

---

## 📖 使用指南

### 基本使用

```python
from pipeline.clarification.clarification_graph import create_clarification_graph
from pipeline.retrieval.retrieval_graph import create_retrieval_graph

# 1. 创建意图澄清子图
clarification_graph = create_clarification_graph()

# 2. 用户输入
user_input = "我想找COVID-19疫苗的文献"

# 3. 执行意图澄清
clarification_result = clarification_graph.invoke({
    "user_input": user_input
})

# 4. 获取澄清后的意图参数
intent_params = clarification_result['intent_params']

# 5. 创建检索子图
retrieval_graph = create_retrieval_graph()

# 6. 执行检索
retrieval_result = retrieval_graph.invoke({
    "intent_params": intent_params
})

# 7. 获取结果
filtered_papers = retrieval_result['filtered_papers']
print(f"检索到 {len(filtered_papers)} 篇论文")

# 8. 查看已下载的论文
downloaded = [p for p in filtered_papers if p.download_status == "success"]
print(f"成功下载 {len(downloaded)} 篇")
```

### 快速示例

```python
from pipeline.retrieval.agents.paper_search import paper_search_agent
from pipeline.retrieval.agents.download import download_agent_sync
from state.retrieval_state import RetrievalState
from models.clarified_intent import ClarifiedIntent

# 直接检索（跳过意图澄清）
intent = ClarifiedIntent(
    entities=["COVID-19", "SARS-CoV-2"],
    properties=["vaccine", "efficacy"],
    conditions={"year": "2020-2024"}
)

state = RetrievalState(intent_params=intent)

# 执行检索
state = paper_search_agent(state)
print(f"OpenAlex检索: {len(state['papers'])} 篇")

# 执行下载
state = download_agent_sync(state)
print(f"下载成功: {len([p for p in state['papers'] if p.download_status == 'success'])} 篇")
```

---

## 🔧 核心功能

### 1. 意图澄清 (Intent Clarification)

自动识别用户查询中的三个关键要素：

- **实体 (Entities)**: 研究对象（材料、化合物、天体等）
- **属性 (Properties)**: 关注的性质（力学性能、物理常数等）
- **条件 (Conditions)**: 约束条件（温度、时间、实验类型等）

**示例**:
```
输入: "高温超导材料的临界温度"
输出:
  entities: ["高温超导材料"]
  properties: ["临界温度"]
  conditions: {}
```

### 2. 多源检索

#### OpenAlex检索
- 检索速度快
- 数据覆盖全面
- 包含引用关系

#### PubMed检索
- 医学领域专业
- 数据质量高
- 支持PMC全文链接

**特点**:
- 并行检索，提高效率
- PubMed论文自动+10%评分加权
- 统一数据格式

### 3. 引用扩展

基于高质量种子论文扩展引用网络：

**策略**:
1. OpenAlex种子：Top 5高引用论文
2. PubMed种子：Top 5高引用论文
3. 每个种子扩展其引用论文
4. 自动去重

**效果**:
- 从初始100篇扩展到175+篇
- 发现相关高质量论文

### 4. 智能下载 (Waterfall策略)

多源下载，按优先级依次尝试：

```
1. pdf_url (OpenAlex直接链接)
2. oa_url (OpenAlex开放获取链接)
3. unpaywall_best_pdf (Unpaywall最佳PDF)
4. unpaywall_alt_1_pdf (Unpaywall备用1)
5. unpaywall_alt_2_pdf (Unpaywall备用2)
   ...
6. unpaywall_alt_N_pdf (Unpaywall备用N)
7. nature_scraper (Nature专用，自动检测)
8. CORE API
```

**关键特性**:

- **Unpaywall多源** - 支持10+个备用源
- **Nature自动检测** - 识别nature.com域名自动切换scraper
- **文件验证** - PDF文件头验证、大小检查
- **失败重试** - 自动降级到下一个源

---

## 📊 性能数据

### V2.0 vs V1.2 对比

| 指标 | V1.2 | V2.0 | 提升 |
|------|------|------|------|
| 数据源 | 1个 | 2个 | +100% |
| 初始检索 | 50篇 | 100篇 | +100% |
| 引用扩展 | 0篇 | 75篇 | 新增 |
| 最终论文数 | 82篇 | 175篇 | +113% |
| 下载成功率 | ~40% | 37.4% | - |

### 下载来源分布（实测数据）

| 来源 | 数量 | 占比 |
|------|------|------|
| pdf_url | 24篇 | 35.8% |
| oa_url | 11篇 | 16.4% |
| **Unpaywall多源** | **32篇** | **47.8%** |

**关键发现**:
- Unpaywall贡献近一半成功下载
- 备用源贡献是best源的4.3倍
- 使用多源策略比只用best源提升5.3倍

---

## 🔍 API文档

### 核心类

#### ClarifiedIntent
```python
from models.clarified_intent import ClarifiedIntent

intent = ClarifiedIntent(
    entities=["COVID-19"],           # 研究对象
    properties=["vaccine"],          # 关注属性
    conditions={"year": "2020-2024"} # 约束条件
)
```

#### PaperMetadata
```python
from models.paper_metadata import PaperMetadata

paper = PaperMetadata(
    id="W1234567890",
    title="Paper Title",
    authors=["Author 1", "Author 2"],
    doi="10.1234/example",
    pdf_url="https://...",
    oa_url="https://...",
    source_db="openalex"  # 或 "pubmed"
)
```

### 核心函数

#### 检索函数

```python
from tools.openalex.search_papers import search_papers

papers = search_papers(
    query="COVID-19 vaccine",
    max_results=50,
    year_range=(2020, 2024)
)
```

```python
from tools.pubmed.search_pubmed import search_pubmed

papers = search_pubmed(
    query="COVID-19 vaccine efficacy",
    max_results=50
)
```

#### 下载函数

```python
from tools.download.download_with_waterfall import download_with_waterfall

result = download_with_waterfall(
    paper=paper_metadata,
    save_dir="./downloads"
)

# 返回:
# {
#   "success": True/False,
#   "local_path": "./downloads/W123.pdf",
#   "source": "unpaywall_alt_3_pdf",
#   "file_size": 1234567,
#   "error": None
# }
```

---

## ⚙️ 配置说明

### configs/constants.py

主要配置项：

```python
# LLM模型选择
DEFAULT_MODEL = "qwen3.7-plus"  # 默认模型
FAST_MODEL = "qwen-turbo"       # 快速模型
SMART_MODEL = "qwen-max"        # 智能模型

# OpenAlex配置
OPENALEX_EMAIL = "your-email@example.com"

# PubMed配置
PUBMED_EMAIL = "your-email@example.com"

# Unpaywall配置
UNPAYWALL_EMAIL = "lijiamingeric28@gmail.com"

# 下载配置
DEFAULT_PAPERS_DIR = "./data/papers"
MAX_DOWNLOAD_RETRIES = 3
DOWNLOAD_TIMEOUT = 60  # 秒
```

### 自定义配置

创建 `configs/openalex_config.py` (可选):
```python
OPENALEX_EMAIL = "your-email@example.com"
OPENALEX_API_KEY = "your-api-key"  # 可选
```

---

## 🐛 故障排除

### 常见问题

#### 1. Unpaywall返回422错误

**原因**: 邮箱配置问题

**解决**:
```bash
export UNPAYWALL_EMAIL=your-email@example.com
```

或在代码中设置：
```python
import os
os.environ['UNPAYWALL_EMAIL'] = 'your-email@example.com'
```

#### 2. 下载失败率高

**可能原因**:
- 付费期刊（Nature、Lancet等）
- 网络问题
- URL过期

**解决**:
- 检查日志查看具体失败原因
- 使用机构VPN访问
- 更新Unpaywall邮箱配置

#### 3. PubMed检索慢

**原因**: NCBI API限制（每秒3次请求）

**解决**:
- 降低max_results
- 使用API key可提升到每秒10次
- 分批检索

#### 4. Nature论文下载失败

**原因**: Nature.com需要更复杂的认证

**解决**:
- 使用机构访问
- 尝试Unpaywall备用源
- 手动下载

---

## 👨‍💻 开发指南

### 添加新的下载源

1. **创建下载器**
   ```python
   # tools/download/your_scraper.py
   def download_from_your_source(url, output_path):
       # 实现下载逻辑
       return {
           "success": True/False,
           "error": None
       }
   ```

2. **集成到Waterfall**
   ```python
   # 在 download_with_waterfall.py 中
   from tools.download.your_scraper import download_from_your_source
   
   # 在sources列表中添加
   sources.append(("your_source", your_url))
   
   # 在循环中添加检测逻辑
   if 'your-domain.com' in url:
       result = download_from_your_source(url, save_path)
   ```

### 添加新的检索源

1. **创建检索函数**
   ```python
   # tools/your_source/search.py
   def search_your_source(query, max_results=50):
       # 实现检索逻辑
       papers = []
       # ...
       return papers
   ```

2. **创建Agent**
   ```python
   # pipeline/retrieval/agents/your_agent.py
   def your_search_agent(state: RetrievalState) -> dict:
       papers = search_your_source(query)
       return {"your_papers": papers}
   ```

3. **集成到检索流程**
   - 在retrieval_graph.py中添加节点
   - 更新状态定义

### 代码规范

- 使用Type Hints
- 添加Docstring
- 遵循PEP 8
- 添加日志记录

---

## 📄 许可证

MIT License

---

## 🤝 贡献

欢迎提交Issue和Pull Request！

---

## 📧 联系方式

如有问题，请通过以下方式联系：

- Email: lijiamingeric28@gmail.com

---

## 🙏 致谢

- **OpenAlex** - 开放的学术数据库
- **PubMed/NCBI** - 生物医学文献数据库
- **Unpaywall** - 开放获取论文查找服务
- **LangGraph** - 状态机框架

---

**最后更新**: 2026-07-14
