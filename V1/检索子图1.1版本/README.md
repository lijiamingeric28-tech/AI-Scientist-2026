# 科学文献检索系统 V1.0

完整的端到端学术论文检索与下载系统

## 功能特性

- 意图澄清：智能理解用户查询意图
- 查询扩展：自动扩展同义词和相关术语
- 论文检索：基于OpenAlex API的大规模检索
- 引用扩展：通过引用网络发现相关论文
- 智能过滤：综合评分和排序
- PDF下载：多源Waterfall策略自动下载

## 系统架构

```
用户输入
  ↓
意图澄清子图（LLM理解）
  ↓
查询扩展（同义词）
  ↓
论文检索（OpenAlex）
  ↓
引用扩展（引用网络）
  ↓
过滤排序（综合评分）
  ↓
PDF下载（多源策略）
  ↓
输出：论文PDF
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置API密钥

在`.env`文件中配置：

```bash
QWEN_API_KEY=your_qwen_api_key
OPENALEX_API_KEY=your_email@example.com
UNPAYWALL_EMAIL=your_email@example.com
```

### 3. 运行系统

```bash
python app.py
```

### 4. 输入查询

```
示例查询：
- Ti-6Al-4V在高温下的抗拉强度
- 铝合金7075的屈服强度
- 304不锈钢的硬度数据
```

## 项目结构

```
科学文献检索系统V1.0/
├── app.py                 # 主入口
├── .env                   # API配置
├── requirements.txt       # 依赖
├── pipeline/              # 核心流程
│   ├── intent/           # 意图澄清子图
│   ├── retrieval/        # 检索子图
│   └── main_graph.py     # 主图
├── tools/                # 工具函数
│   ├── evaluate_intent/
│   ├── ask_user_guided/
│   ├── confirm_intent/
│   ├── expand_query/
│   ├── paper_search/
│   ├── citation_expansion/
│   ├── filter_rank/
│   └── download/
├── models/               # 数据模型
├── state/                # State定义
├── configs/              # 配置
├── utils/                # 工具类
└── data/                 # 输出数据
    └── papers/           # 下载的PDF
```

## 下载策略

系统使用Waterfall策略，依次尝试多个源：

1. **pdf_url** - OpenAlex直接PDF链接
2. **oa_url** - OpenAlex开放获取链接
3. **unpaywall** - Unpaywall API
4. **core** - CORE API

每个源失败后自动尝试下一个，直到成功或所有源都失败。

## 核心技术

- **LangGraph**: 状态图编排
- **通义千问**: 意图理解和查询扩展
- **OpenAlex API**: 论文检索
- **Unpaywall API**: 开放获取链接
- **HTML Fallback**: 从HTML页面提取PDF链接

## 注意事项

- 首次运行会进行意图澄清（交互式追问）
- 下载成功率取决于论文的开放获取情况
- 系统只下载合法的开放获取论文
- 完整流程约5-10分钟

## 许可

本项目仅供学习和研究使用。

---

**版本**: V1.0  
**状态**: 生产就绪  
**更新日期**: 2025-07-13
