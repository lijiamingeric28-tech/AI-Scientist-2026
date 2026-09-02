# 科学文献检索系统 V1.2

[![Version](https://img.shields.io/badge/version-1.2.0-blue.svg)](https://github.com/lijiamingeric/retrieval-subgraph)
[![Python](https://img.shields.io/badge/python-3.8+-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

完整的端到端学术论文检索与下载系统

## 🎉 V1.2 新特性

### ⚡ 性能大幅提升
- **下载速度提升488%**: 从0.25篇/秒 → 1.47篇/秒
- **总耗时减少71%**: 从450秒 → 129秒
- **成功率提升**: 从31-35% → 40.6%

### 🚀 高并发下载
- 15个并发（从3提升）
- 双重信号量控制（全局 + 每域名限制）
- HTTP连接池优化

### 📊 智能监控
- 实时进度条
- 详细统计报告
- 按来源/域名分析

详见 [CHANGELOG.md](CHANGELOG.md)

---

## 功能特性

- ✅ **意图澄清**：智能理解用户查询意图
- ✅ **查询扩展**：自动扩展同义词和相关术语
- ✅ **论文检索**：基于OpenAlex API的大规模检索
- ✅ **引用扩展**：通过引用网络发现相关论文
- ✅ **智能过滤**：综合评分和排序
- ✅ **PDF下载**：多源Waterfall策略自动下载
- ✨ **高并发下载**：15并发，速度提升5倍（新）
- ✨ **实时进度**：下载进度实时显示（新）
- ✨ **详细统计**：完整的性能分析报告（新）

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
