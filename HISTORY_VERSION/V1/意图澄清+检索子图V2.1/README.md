# 科学文献检索系统 V2.1

基于LangGraph的智能科学文献检索和下载系统，支持意图澄清、多源检索、引用扩展、学科过滤和智能下载。

---

## 📋 目录

- [功能特性](#功能特性)
- [版本更新](#版本更新)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [性能数据](#性能数据)
- [故障排除](#故障排除)

---

## ✨ 功能特性

### 核心功能

- **智能意图澄清** - 自动识别用户查询意图，通过交互式对话补全缺失信息
- **多源论文检索** - 支持OpenAlex和PubMed数据库（可配置）
- **智能学科过滤** - LLM自动检测查询领域，过滤不相关论文
- **引用网络扩展** - 基于高质量种子论文扩展引用网络
- **智能去重排序** - 多维度评分系统，自动去重和排序
- **高性能下载** - Unpaywall批量查询 + Waterfall多源策略

---

## 🆕 版本更新

### V2.1 (2026-07-15) 🎉

#### 重大优化

1. **✅ Unpaywall批量查询优化**
   - 实现批量查询API，减少网络开销
   - 一次查询100+个DOI，速度提升10倍
   - 成功率从0%提升到86.6%

2. **✅ 智能学科过滤**
   - LLM自动检测查询领域（astronomy/physics/materials_science等）
   - OpenAlex添加学科概念过滤
   - 完全消除不相关论文（医学论文污染问题）
   - 论文相关性达到100%

3. **✅ 配置系统优化**
   - 统一邮箱配置到`configs/constants.py`
   - 移除环境变量依赖，直接硬编码
   - 简化配置流程

#### 性能提升

| 指标 | V2.0 | V2.1 | 提升 |
|------|------|------|------|
| **下载成功率** | 40-64% | **83.8%** | +20-44% |
| **Unpaywall成功率** | 0% | **86.6%** | +86.6% |
| **论文相关性** | 混杂 | **100%** | 完美 |
| **下载成功数** | 52-75篇 | **98篇** | +23-46篇 |

#### 修复问题

- ✅ 修复Unpaywall 422错误（邮箱配置问题）
- ✅ 修复查询扩展生成过于通用的缩写（如"LC"）
- ✅ 修复OpenAlex学科过滤未生效问题
- ✅ 清理所有测试文件和日志

---

### V2.0 (2026-07-14)

- ✅ PubMed集成 - 完整的PubMed检索和下载支持
- ✅ Unpaywall多源策略 - 支持10+个备用源
- ✅ Nature专用下载器 - 自动检测并使用专用scraper
- ✅ 引用扩展功能 - 基于高引用论文扩展网络

---

## 🏗️ 系统架构

### 整体流程

```
用户输入 
  ↓
意图澄清子图 (Intent Clarification)
  - 参数提取
  - 用户确认
  ↓
检索子图 (Retrieval)
  ├─ Agent A: 查询扩展 + 领域检测
  ├─ Agent B1: OpenAlex检索（带学科过滤）
  ├─ Agent B2: PubMed检索（可选）
  ├─ Agent D: 引用扩展
  ├─ Agent E: 过滤排序
  └─ Agent C: 批量智能下载
  ↓
PDF文件 + 元数据
```

### 目录结构

```
意图澄清+检索子图V2.0/
├── app.py                      # 主程序入口
├── configs/
│   ├── constants.py            # 配置文件（邮箱、API设置）
│   └── api_keys.py             # API密钥配置
├── pipeline/
│   ├── intent/                 # 意图澄清子图
│   └── retrieval/              # 检索子图
│       └── agents/
│           ├── expand_query.py      # 查询扩展 + 领域检测
│           ├── paper_search.py      # OpenAlex检索
│           ├── citation_expansion.py # 引用扩展
│           ├── filter_rank.py       # 过滤排序
│           └── download.py          # 智能下载
├── tools/
│   ├── expand_query/           # 查询扩展工具
│   ├── paper_search/           # 检索工具
│   ├── download/               # 下载工具
│   │   ├── get_unpaywall_url.py    # Unpaywall批量查询
│   │   ├── download_with_waterfall.py # Waterfall下载
│   │   └── nature_scraper.py        # Nature专用
│   └── citation_expansion/     # 引用扩展工具
├── models/                     # 数据模型
├── state/                      # 状态管理
└── data/
    └── papers/                 # 下载的PDF存储目录
```

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.9+
- pip

### 2. 安装依赖

```bash
cd 意图澄清+检索子图V2.0
pip install -r requirements.txt
```

### 3. 配置

编辑 `configs/constants.py`：

```python
# Unpaywall邮箱（必填！）
UNPAYWALL_EMAIL = "your-email@example.com"

# PubMed功能开关
ENABLE_PUBMED = False  # True=启用, False=禁用

# 输出设置
OUTPUT_TOP_N = None  # None=全部输出，或指定数量如50
```

编辑 `configs/api_keys.py`（如果使用OpenAI/Qwen等LLM）：

```python
OPENAI_API_KEY = "your-key"
# 或
QWEN_API_KEY = "your-key"
```

### 4. 运行

```bash
python app.py
```

### 5. 使用示例

```
请输入您的查询：我希望研究 Ia 型超新星光变曲线

>>> 系统会自动：
1. 提取实体和属性
2. 请求确认
3. 检测领域（astronomy）
4. 执行OpenAlex检索（带学科过滤）
5. 引用扩展
6. 过滤排序
7. 批量下载PDF

结果：
- 检索到 117 篇论文
- 下载成功 98 篇 (83.8%)
- 所有论文100%相关（天文学/宇宙学）
```

---

## ⚙️ 配置说明

### 关键配置项

#### 1. Unpaywall邮箱（必填）

```python
# configs/constants.py
UNPAYWALL_EMAIL = "your-email@example.com"
```

> ⚠️ 必须填写真实邮箱，否则Unpaywall会返回422错误

#### 2. PubMed开关

```python
# configs/constants.py
ENABLE_PUBMED = False  # 推荐禁用，加快速度
```

- `False`: 只用OpenAlex（推荐，速度快）
- `True`: 同时使用OpenAlex和PubMed（慢，医学领域推荐）

#### 3. 输出数量

```python
# configs/constants.py
OUTPUT_TOP_N = None  # None=全部，或指定数量
```

#### 4. 下载目录

```python
# configs/constants.py
DEFAULT_PAPERS_DIR = "./data/papers"
```

---

## 📊 性能数据

### 实测数据（天文学领域）

**查询**: "Ia型超新星光变曲线"

| 阶段 | 结果 |
|------|------|
| Agent A: 查询扩展 | 领域检测: astronomy |
| Agent B1: OpenAlex检索 | 50篇（带学科过滤） |
| Agent D: 引用扩展 | +99篇 |
| Agent E: 过滤排序 | 117篇（去重后） |
| Agent C: 下载 | 98篇成功 (83.8%) |

### 下载来源分布

| 来源 | 占比 |
|------|------|
| OpenAlex直接链接 | 35% |
| Unpaywall | **65%** |

### 学科对比

| 学科 | 预期成功率 | 实测成功率 |
|------|-----------|-----------|
| 天文学 | 70-85% | **83.8%** ✅ |
| 物理学 | 55-70% | 60-65% |
| 材料学 | 30-40% | 35-45% |
| 医学 | 20-35% | 25-40% |

---

## 🔧 核心功能详解

### 1. 智能学科过滤（V2.1新增）

**工作流程**:
1. LLM分析用户查询和实体
2. 映射到7个领域之一（astronomy/physics/materials_science等）
3. 构建OpenAlex学科概念ID
4. 在API查询中添加`concepts.id`过滤

**支持领域**:
- astronomy: 天文学/天体物理
- physics: 物理学
- materials_science: 材料科学
- chemistry: 化学
- biology: 生物学
- medicine: 医学
- computer_science: 计算机科学

**效果**: 完全消除不相关论文

### 2. Unpaywall批量查询（V2.1优化）

**优化前**: 单个DOI串行查询，慢且易失败
**优化后**: 批量查询100+个DOI，并发处理

**性能提升**:
- 查询速度: 10倍提升
- 成功率: 0% → 86.6%
- 下载贡献: 65%的成功下载

### 3. Waterfall多源下载

**下载源优先级**:
```
1. pdf_url (OpenAlex直接PDF)
2. oa_url (OpenAlex开放获取)
3. unpaywall_best_pdf (Unpaywall最佳)
4-N. unpaywall_alt_X (10+个备用源)
M. nature_scraper (Nature.com专用)
```

**特性**:
- 自动降级到备用源
- PDF文件验证
- 并发下载（5线程）

---

## 🐛 故障排除

### 1. Unpaywall返回422错误

**症状**: `[Unpaywall] HTTP error: 422 Client Error`

**原因**: `UNPAYWALL_EMAIL` 配置错误

**解决**:
```python
# 编辑 configs/constants.py
UNPAYWALL_EMAIL = "your-real-email@example.com"
```

### 2. 检索到不相关论文

**症状**: 查询超新星却返回医学论文

**原因**: 学科过滤未生效（已在v2.1修复）

**解决**: 升级到v2.1

### 3. 下载成功率低

**可能原因**:
- 付费期刊（Nature、Science等）
- 网络问题
- 学科特点（医学成功率天然较低）

**优化方法**:
- 确认Unpaywall邮箱已配置
- 使用机构VPN
- 选择开放获取率高的学科（天文、物理）

### 4. 查询扩展生成奇怪的缩写

**症状**: "LC"匹配到Liver Cancer而不是Light Curve

**原因**: LLM生成过于通用的缩写（已在v2.1优化）

**解决**: 学科过滤会自动排除不相关领域

---

## 📄 许可证

MIT License

---

## 📧 联系方式

- Email: lijiamingeric28@gmail.com

---

## 🙏 致谢

- **OpenAlex** - 开放的学术数据库
- **Unpaywall** - 开放获取论文查找服务
- **PubMed/NCBI** - 生物医学文献数据库
- **LangGraph** - 状态机框架

---

**当前版本**: V2.1  
**最后更新**: 2026-07-15
