# pdf_url 和 oa_url 详解

**文档版本**: v1.0  
**更新日期**: 2026-07-14

---

## 快速回答

### pdf_url (Primary Location PDF URL)

**来源**: `item["primary_location"]["pdf_url"]`

**定义**: 论文**主要出版位置**的直接PDF下载链接

**特点**:
- 指向论文首次发表的期刊/会议的PDF
- 通常是**出版商官方网站**的PDF链接
- 可能需要订阅或付费才能访问
- **经常为空**（很多出版商不提供直接PDF链接）

**示例**:
```json
{
  "primary_location": {
    "source": {
      "display_name": "Nature"
    },
    "pdf_url": "https://www.nature.com/articles/s41586-020-2649-2.pdf"
    //          ↑ Nature官网的PDF链接（通常需要付费）
  }
}
```

---

### oa_url (Open Access URL)

**来源**: `item["open_access"]["oa_url"]`

**定义**: 论文的**开放获取版本**链接（免费可访问）

**特点**:
- 指向论文的**免费开放版本**
- 可能是出版商网站、预印本服务器、机构仓库等
- **数据主要来自Unpaywall**
- 如果论文不是开放获取，则为`null`

**示例**:
```json
{
  "open_access": {
    "is_oa": true,
    "oa_status": "gold",  // 金色OA：出版商提供的免费版本
    "oa_url": "https://doi.org/10.7717/peerj.4375"
    //        ↑ 免费可访问的链接
  }
}
```

---

## 详细对比

| 特性 | pdf_url | oa_url |
|------|---------|--------|
| **位置** | `primary_location.pdf_url` | `open_access.oa_url` |
| **含义** | 主要出版位置的PDF | 开放获取版本链接 |
| **访问** | 可能需要付费/订阅 | **免费开放** |
| **来源** | 出版商官网 | 多种来源（出版商/预印本/仓库） |
| **数据源** | OpenAlex自己抓取 | **主要来自Unpaywall** |
| **格式** | 通常是直接PDF链接 | 可能是网页或PDF |
| **为空率** | **很高**（70-80%） | 中等（30-40%） |
| **优先级** | 下载策略第1位 | 下载策略第2位 |

---

## 实际案例

### 案例1：付费期刊文章

```json
{
  "title": "Graphene mechanical properties study",
  
  "primary_location": {
    "source": {"display_name": "Nature Materials"},
    "pdf_url": "https://www.nature.com/articles/nmat5000.pdf"
    //          ↑ Nature官网PDF（需要订阅）
  },
  
  "open_access": {
    "is_oa": true,
    "oa_url": "https://arxiv.org/pdf/2001.12345.pdf"
    //        ↑ arXiv上的免费预印本版本
  }
}
```

**解释**:
- `pdf_url`: 指向Nature官网的正式出版版本（需要付费）
- `oa_url`: 指向arXiv的免费预印本版本
- 系统会先尝试`pdf_url`，失败后尝试`oa_url`

---

### 案例2：金色开放获取期刊

```json
{
  "title": "Machine learning for materials",
  
  "primary_location": {
    "source": {"display_name": "MDPI Materials"},
    "pdf_url": null  // ← MDPI不提供直接PDF链接
  },
  
  "open_access": {
    "is_oa": true,
    "oa_status": "gold",
    "oa_url": "https://www.mdpi.com/1996-1944/14/8/1234/pdf"
    //        ↑ MDPI提供的免费PDF
  }
}
```

**解释**:
- `pdf_url`: 为空（MDPI期刊不在primary_location提供PDF）
- `oa_url`: 指向MDPI官网的免费PDF
- 系统会跳过`pdf_url`，直接使用`oa_url`

---

### 案例3：封闭获取论文

```json
{
  "title": "Proprietary research results",
  
  "primary_location": {
    "source": {"display_name": "Elsevier Journal"},
    "pdf_url": null  // ← 没有直接PDF链接
  },
  
  "open_access": {
    "is_oa": false,  // ← 不是开放获取
    "oa_url": null   // ← 没有免费版本
  }
}
```

**解释**:
- `pdf_url`: 为空
- `oa_url`: 为空（完全封闭，没有免费版本）
- 系统会尝试Unpaywall和CORE作为fallback

---

## 开放获取类型

OpenAlex/Unpaywall定义的开放获取状态：

| 类型 | 说明 | 示例 |
|------|------|------|
| **gold** | 出版商提供的官方免费版本 | PLOS ONE, MDPI期刊 |
| **green** | 作者自存档版本 | arXiv预印本，机构仓库 |
| **hybrid** | 付费期刊中的单篇开放文章 | Nature论文作者付费开放 |
| **bronze** | 出版商网站免费但无明确许可 | 部分期刊的临时免费 |
| **closed** | 完全封闭，无免费版本 | 大多数传统付费期刊 |

---

## 下载策略中的使用

### Waterfall策略顺序

```python
# 1. pdf_url (主要出版位置PDF)
if pdf_url:
    try_download(pdf_url)  # 尝试出版商官方PDF
    
# 2. oa_url (开放获取链接)  
if oa_url:
    try_download(oa_url)   # 尝试免费开放版本
    
# 3. unpaywall (Unpaywall API)
unpaywall_url = get_unpaywall_url(doi)
if unpaywall_url:
    try_download(unpaywall_url)  # 通常与oa_url相同
    
# 4. core (CORE API)
core_url = get_core_url(doi)
if core_url:
    try_download(core_url)
```

### 为什么这个顺序？

1. **pdf_url优先**: 
   - 如果能访问，质量最高（正式出版版本）
   - 但成功率低（需要订阅）

2. **oa_url第二**:
   - 免费且合法
   - 可能是预印本或作者版本
   - 成功率中等

3. **unpaywall第三**:
   - 作为fallback
   - 数据与oa_url高度重复（因为OpenAlex就是用Unpaywall的数据）

4. **core最后**:
   - 最后的尝试
   - 可能找到机构仓库中的版本

---

## 统计数据（基于实际测试）

### 测试结果（96篇论文）

| 字段 | 非空数量 | 非空率 | 下载成功 | 成功率 |
|------|---------|--------|---------|--------|
| **pdf_url** | ~30篇 | 31% | 16篇 | 53% |
| **oa_url** | ~65篇 | 68% | 14篇 | 22% |
| **both null** | ~5篇 | 5% | - | - |

**观察**:
- `pdf_url`非空率低（31%），但成功率高（53%）
- `oa_url`非空率高（68%），但成功率低（22%）
- 两者结合，总下载成功率达到30-35%

---

## OpenAlex与Unpaywall的关系

### 关键事实

**OpenAlex的`oa_url`数据来源于Unpaywall**

根据[OpenAlex文档](https://docs.openalex.org/api-entities/works/work-object#open_access):

> "The `oa_url` field comes from Unpaywall's `best_oa_location.url_for_pdf`"

**这就是为什么**:
- Unpaywall API返回的URL与`oa_url`高度重复
- 在我们的测试中，Unpaywall没有成功下载任何论文
- 因为`oa_url`已经提供了相同的链接

---

## 代码示例

### 解析OpenAlex响应

```python
def parse_openalex_item(item):
    # 提取pdf_url（主要出版位置）
    pdf_url = item.get("primary_location", {}).get("pdf_url")
    
    # 提取oa_url（开放获取链接）
    open_access = item.get("open_access", {})
    is_oa = open_access.get("is_oa", False)
    oa_url = open_access.get("oa_url")
    
    return {
        "pdf_url": pdf_url,      # 可能为None
        "oa_url": oa_url,        # 可能为None
        "is_oa": is_oa           # True/False
    }
```

### 下载策略实现

```python
def download_with_waterfall(paper):
    sources = [
        ("pdf_url", paper.pdf_url),
        ("oa_url", paper.oa_url),
        ("unpaywall", get_unpaywall_url(paper.doi)),
        ("core", get_core_url(paper.doi))
    ]
    
    for source_name, url in sources:
        if not url:
            continue  # 跳过空URL
            
        result = download_from_url(url)
        
        if result.success:
            return {
                "success": True,
                "source": source_name,
                "local_path": result.path
            }
    
    return {"success": False, "error": "All sources failed"}
```

---

## 常见问题

### Q1: 为什么pdf_url经常为空？

**A**: 很多出版商不提供直接的PDF链接，而是提供一个网页（landing page），用户需要在网页上点击下载按钮。OpenAlex只记录直接PDF链接。

### Q2: oa_url和pdf_url可以同时存在吗？

**A**: 可以！对于金色开放获取期刊，两者可能指向同一个PDF：
```json
{
  "pdf_url": "https://www.mdpi.com/1996-1944/14/8/1234.pdf",
  "oa_url": "https://www.mdpi.com/1996-1944/14/8/1234/pdf"
}
```

### Q3: 如果两个都为空怎么办？

**A**: 系统会尝试Unpaywall和CORE API作为fallback。如果全部失败，标记为下载失败。

### Q4: 为什么不直接用Unpaywall，跳过OpenAlex？

**A**: 
1. OpenAlex已经包含了Unpaywall的数据（oa_url）
2. OpenAlex还提供了额外的pdf_url（主要出版位置）
3. OpenAlex的搜索功能更强大
4. 一次API调用获取所有信息更高效

### Q5: oa_url一定是PDF吗？

**A**: 不一定。oa_url可能是：
- 直接PDF链接（最理想）
- 论文网页（需要进一步解析）
- DOI链接（重定向到网页）
- 机构仓库页面

---

## 总结

### 关键要点

1. **pdf_url**: 主要出版位置的PDF（通常需要付费）
2. **oa_url**: 开放获取版本（免费，来自Unpaywall）
3. **两者互补**: pdf_url质量高但成功率低，oa_url免费但可能是预印本
4. **Unpaywall关系**: OpenAlex的oa_url就是从Unpaywall获取的
5. **下载策略**: 按pdf_url → oa_url → unpaywall → core顺序尝试

### 实际应用建议

✅ **推荐做法**:
- 保持现有的waterfall策略
- 先尝试pdf_url（出版商官方）
- 再尝试oa_url（免费开放）
- Unpaywall作为fallback（虽然重复率高）

⚠️ **注意事项**:
- 不要期望pdf_url和oa_url都有值
- 做好两者都为空的fallback处理
- oa_url不一定是直接PDF，可能需要HTML解析

---

**相关文档**:
- [OpenAlex API文档](https://docs.openalex.org/api-entities/works/work-object)
- [Unpaywall API文档](https://unpaywall.org/products/api)
- 项目测试报告: `test_results/UNPAYWALL_INTEGRATION_REPORT.md`

**最后更新**: 2026-07-14
