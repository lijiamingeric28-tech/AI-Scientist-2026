# 下载系统升级计划

**版本**: v2.0  
**日期**: 2026-07-14  
**目标**: 移除Unpaywall冗余调用 + 提高下载并发速度

---

## 📊 当前状态分析

### 现有配置

```python
# configs/constants.py
DOWNLOAD_MAX_CONCURRENT = 3    # 当前并发数：3
DOWNLOAD_TIMEOUT = 30          # 单个下载超时：30秒
DOWNLOAD_MAX_RETRIES = 2       # 重试次数：2次
```

### 性能数据（基于实际测试）

| 指标 | 数值 |
|------|------|
| 待下载论文 | 96篇 |
| 成功下载 | 30-34篇 |
| 总耗时 | ~380秒 (6.3分钟) |
| 平均下载速度 | ~3.96秒/论文 |
| 下载阶段占比 | 80-84% |

### 问题识别

1. ⚠️ **Unpaywall冗余**: 与oa_url重复率接近100%，无实际贡献
2. ⚠️ **并发数过低**: 仅3个并发，资源利用率低
3. ⚠️ **下载耗时占比过高**: 80%的时间在下载

---

## 🎯 升级目标

### 主要目标

1. ✅ **移除Unpaywall冗余调用** - 减少API调用开销
2. ✅ **提高下载并发** - 从3并发提升到10-20并发
3. ✅ **优化下载速度** - 将下载时间从380秒降至150秒以内

### 预期效果

| 指标 | 当前 | 目标 | 改善 |
|------|------|------|------|
| 并发数 | 3 | 15 | +400% |
| 下载总耗时 | 380秒 | 120-150秒 | -60% |
| 总流程耗时 | 450秒 | 200-250秒 | -50% |
| API调用次数 | 98次Unpaywall | 0次 | -100% |

---

## 📋 升级计划

### 阶段1: 移除Unpaywall冗余调用 🔧

**优先级**: ⭐⭐⭐⭐⭐ (高)  
**难度**: ⭐ (简单)  
**风险**: 低  

#### 1.1 修改waterfall策略

**文件**: `tools/download/download_with_waterfall.py`

**当前代码**:
```python
sources = [
    ("pdf_url", paper.pdf_url),
    ("oa_url", paper.oa_url),
    ("unpaywall", get_unpaywall_url(paper.doi) if paper.doi else None),  # ← 移除
    ("core", get_core_url(paper.doi) if paper.doi else None)
]
```

**修改后**:
```python
sources = [
    ("pdf_url", paper.pdf_url),
    ("oa_url", paper.oa_url),
    # Unpaywall已移除（与oa_url重复）
    ("core", get_core_url(paper.doi) if paper.doi else None)
]
```

#### 1.2 更新导入语句

**移除**:
```python
from tools.download.get_unpaywall_url import get_unpaywall_url  # 删除此行
```

#### 1.3 更新注释和文档

**修改**:
```python
"""
使用Waterfall策略从多个源依次尝试下载

Waterfall顺序:
    1. pdf_url（OpenAlex直接PDF链接）
    2. oa_url（OpenAlex开放获取链接，来自Unpaywall数据）
    3. core（CORE API）
    
注: Unpaywall已移除，因为其数据已包含在oa_url中
"""
```

#### 1.4 保留代码（可选）

**将Unpaywall相关代码移至backup目录**:
```bash
mkdir -p tools/download/backup
mv tools/download/get_unpaywall_url.py tools/download/backup/
```

**预期效果**:
- ✅ 减少98次API调用
- ✅ 节省约10-15秒（API调用时间）
- ✅ 简化代码逻辑
- ⚠️ 几乎不影响下载成功率（<0.1%）

---

### 阶段2: 提高下载并发 🚀

**优先级**: ⭐⭐⭐⭐⭐ (高)  
**难度**: ⭐⭐ (中等)  
**风险**: 中等  

#### 2.1 调整并发配置

**文件**: `configs/constants.py`

**当前配置**:
```python
DOWNLOAD_MAX_CONCURRENT = 3
DOWNLOAD_TIMEOUT = 30
DOWNLOAD_MAX_RETRIES = 2
```

**推荐配置**:
```python
# ========== 论文下载 ==========
DOWNLOAD_DIR = "./data/papers"
DOWNLOAD_TIMEOUT = 45              # 增加到45秒（防止并发时超时）
DOWNLOAD_MAX_RETRIES = 2           # 保持不变
DOWNLOAD_MAX_CONCURRENT = 15       # 从3提升到15 ← 关键改动
MIN_FILE_SIZE = 10 * 1024          # 10KB
MAX_FILE_SIZE = 50 * 1024 * 1024   # 50MB

# 新增：并发控制
DOWNLOAD_RATE_LIMIT_PER_DOMAIN = 5  # 每域名最大并发
DOWNLOAD_CONNECTION_POOL_SIZE = 20  # HTTP连接池大小
```

#### 2.2 优化异步下载实现

**文件**: `pipeline/retrieval/agents/download.py`

**当前实现分析**:
```python
async def _download_papers_async(papers, download_dir):
    semaphore = Semaphore(DOWNLOAD_MAX_CONCURRENT)  # 简单信号量
    
    async def download_one(paper, idx):
        async with semaphore:
            # 下载逻辑
            pass
```

**优化方案**:

```python
import asyncio
from asyncio import Semaphore
from collections import defaultdict
from urllib.parse import urlparse

async def _download_papers_async(papers, download_dir):
    """优化的异步下载函数"""
    
    # 全局并发限制
    global_semaphore = Semaphore(DOWNLOAD_MAX_CONCURRENT)  # 15
    
    # 每域名并发限制（防止单一服务器过载）
    domain_semaphores = defaultdict(lambda: Semaphore(5))
    
    async def download_one(paper, idx):
        """下载单篇论文（带域名限制）"""
        
        # 获取域名
        sources = [
            ("pdf_url", paper.pdf_url),
            ("oa_url", paper.oa_url),
            ("core", get_core_url(paper.doi) if paper.doi else None)
        ]
        
        for source_name, url in sources:
            if not url:
                continue
            
            # 解析域名
            domain = urlparse(url).netloc
            domain_sem = domain_semaphores[domain]
            
            # 双重信号量：全局 + 域名
            async with global_semaphore:
                async with domain_sem:
                    print(f"\n  [{idx}/{len(papers)}] 下载: {paper.title[:40]}...")
                    
                    # 检查已存在
                    file_path = os.path.join(download_dir, f"{paper.id}.pdf")
                    if check_existing_file(file_path):
                        paper.local_path = file_path
                        paper.download_status = "skipped"
                        print(f"       [SKIP]  文件已存在，跳过")
                        return
                    
                    try:
                        # 异步下载
                        result = await asyncio.to_thread(
                            download_from_url,
                            url,
                            file_path
                        )
                        
                        if result["success"]:
                            paper.local_path = result["local_path"]
                            paper.download_status = "success"
                            paper.download_source = source_name
                            paper.file_size = result.get("file_size", 0)
                            print(f"       [OK] 成功 (来源: {source_name}, 大小: {result.get('file_size', 0)/1024:.1f} KB)")
                            return  # 成功后退出
                        
                    except Exception as e:
                        logger.warning(f"  {paper.id} failed: {e}")
                        continue  # 尝试下一个来源
        
        # 所有来源都失败
        paper.download_status = "failed"
        print(f"       [X] 失败: All sources failed")
    
    # 并发执行所有下载任务
    tasks = [download_one(paper, idx+1) for idx, paper in enumerate(papers)]
    await asyncio.gather(*tasks, return_exceptions=True)
```

**关键改进**:
1. ✅ **双重信号量**: 全局并发 + 每域名并发限制
2. ✅ **域名分组**: 防止单一服务器过载
3. ✅ **异常隔离**: `return_exceptions=True`防止单个失败影响全局

#### 2.3 优化HTTP连接池

**文件**: `tools/download/download_from_url.py`

**当前实现**: 每次请求创建新连接

**优化方案**: 使用连接池

```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 全局会话（连接池）
_session = None

def get_session():
    """获取带连接池的全局Session"""
    global _session
    
    if _session is None:
        _session = requests.Session()
        
        # 配置重试策略
        retry_strategy = Retry(
            total=2,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        
        # 配置HTTP适配器（连接池）
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=20,   # 连接池大小
            pool_maxsize=20,       # 最大连接数
            pool_block=False
        )
        
        _session.mount("http://", adapter)
        _session.mount("https://", adapter)
        
        # 设置默认头
        _session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    return _session


def download_from_url(url, save_path, timeout=45):
    """使用连接池下载"""
    session = get_session()
    
    for attempt in range(1, 4):  # 最多3次尝试
        try:
            response = session.get(url, timeout=timeout, stream=True)
            response.raise_for_status()
            
            # 下载逻辑
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            return {"success": True, "local_path": save_path}
            
        except Exception as e:
            if attempt < 3:
                continue
            return {"success": False, "error": str(e)}
```

**关键改进**:
1. ✅ **连接复用**: 减少TCP握手开销
2. ✅ **连接池**: 支持20个并发连接
3. ✅ **自动重试**: 对临时错误自动重试

---

### 阶段3: 智能下载策略 🧠

**优先级**: ⭐⭐⭐ (中)  
**难度**: ⭐⭐⭐ (复杂)  
**风险**: 低  

#### 3.1 URL去重

**避免重复下载相同URL**

```python
def download_with_waterfall(paper, save_dir):
    """优化的waterfall策略"""
    
    tried_urls = set()  # 记录已尝试的URL
    
    sources = [
        ("pdf_url", paper.pdf_url),
        ("oa_url", paper.oa_url),
        ("core", get_core_url(paper.doi) if paper.doi else None)
    ]
    
    for source_name, url in sources:
        if not url:
            continue
        
        # 规范化URL（去除参数、锚点）
        normalized_url = normalize_url(url)
        
        if normalized_url in tried_urls:
            logger.debug(f"Skipping duplicate URL: {source_name}")
            continue
        
        tried_urls.add(normalized_url)
        
        # 尝试下载
        result = download_from_url(url, save_path)
        if result["success"]:
            return result
    
    return {"success": False, "error": "All sources failed"}


def normalize_url(url):
    """规范化URL（去除参数、锚点）"""
    from urllib.parse import urlparse, urlunparse
    
    parsed = urlparse(url)
    # 去除query和fragment
    normalized = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        '',  # params
        '',  # query
        ''   # fragment
    ))
    return normalized
```

#### 3.2 智能超时

**根据文件大小动态调整超时**

```python
def calculate_timeout(file_size_hint=None):
    """智能计算超时时间"""
    
    if file_size_hint:
        # 假设最低速度 100KB/s
        timeout = max(30, file_size_hint / (100 * 1024) + 10)
        return min(timeout, 120)  # 最多2分钟
    
    return 45  # 默认45秒
```

#### 3.3 下载进度显示

**实时显示总体进度**

```python
from tqdm import tqdm

async def _download_papers_async(papers, download_dir):
    """带进度条的异步下载"""
    
    # 创建进度条
    pbar = tqdm(total=len(papers), desc="下载PDF", unit="篇")
    
    async def download_one_with_progress(paper, idx):
        result = await download_one(paper, idx)
        pbar.update(1)  # 更新进度
        return result
    
    tasks = [download_one_with_progress(paper, idx+1) 
             for idx, paper in enumerate(papers)]
    
    await asyncio.gather(*tasks, return_exceptions=True)
    pbar.close()
```

---

### 阶段4: 监控与统计 📊

**优先级**: ⭐⭐ (低)  
**难度**: ⭐⭐ (中等)  
**风险**: 低  

#### 4.1 下载统计

```python
class DownloadStats:
    """下载统计"""
    
    def __init__(self):
        self.total = 0
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.total_bytes = 0
        self.start_time = None
        self.end_time = None
        
        # 按来源统计
        self.success_by_source = defaultdict(int)
        
        # 按域名统计
        self.success_by_domain = defaultdict(int)
        self.failed_by_domain = defaultdict(int)
    
    def start(self):
        self.start_time = time.time()
    
    def finish(self):
        self.end_time = time.time()
    
    def record_success(self, source, url, file_size):
        self.success += 1
        self.total_bytes += file_size
        self.success_by_source[source] += 1
        
        domain = urlparse(url).netloc
        self.success_by_domain[domain] += 1
    
    def record_failure(self, url):
        self.failed += 1
        domain = urlparse(url).netloc
        self.failed_by_domain[domain] += 1
    
    def record_skip(self):
        self.skipped += 1
    
    def print_summary(self):
        """打印统计摘要"""
        elapsed = self.end_time - self.start_time
        
        print("\n" + "="*80)
        print("下载统计报告")
        print("="*80)
        print(f"\n总计: {self.total} 篇")
        print(f"  成功: {self.success} 篇 ({self.success/self.total*100:.1f}%)")
        print(f"  跳过: {self.skipped} 篇 ({self.skipped/self.total*100:.1f}%)")
        print(f"  失败: {self.failed} 篇 ({self.failed/self.total*100:.1f}%)")
        
        print(f"\n总大小: {self.total_bytes / (1024*1024):.1f} MB")
        print(f"总耗时: {elapsed:.1f} 秒")
        print(f"平均速度: {self.total/(elapsed):.2f} 篇/秒")
        
        print(f"\n按来源统计:")
        for source, count in sorted(self.success_by_source.items(), 
                                    key=lambda x: x[1], reverse=True):
            print(f"  {source:15s}: {count:3d} 篇")
        
        print(f"\nTop 5 成功域名:")
        for domain, count in sorted(self.success_by_domain.items(), 
                                    key=lambda x: x[1], reverse=True)[:5]:
            print(f"  {domain:40s}: {count:3d} 篇")
```

---

## 🚀 实施步骤

### 步骤1: 备份现有代码 ✅

```bash
# 创建备份
cd "E:/整合/意图澄清+检索子图V1.1"
git add .
git commit -m "Backup before download optimization"

# 或手动备份
mkdir -p backups/download_v1
cp -r tools/download backups/download_v1/
cp -r pipeline/retrieval/agents/download.py backups/download_v1/
cp configs/constants.py backups/download_v1/
```

### 步骤2: 阶段1实施（移除Unpaywall）⚡

**预计时间**: 10分钟

1. 修改 `tools/download/download_with_waterfall.py`
2. 移除 `get_unpaywall_url` 导入
3. 更新注释和文档
4. 测试验证

### 步骤3: 阶段2实施（提高并发）⚡⚡

**预计时间**: 30分钟

1. 修改 `configs/constants.py` - 更新并发配置
2. 优化 `pipeline/retrieval/agents/download.py` - 双重信号量
3. 优化 `tools/download/download_from_url.py` - 连接池
4. 测试验证

### 步骤4: 阶段3实施（智能策略）⚡

**预计时间**: 20分钟

1. 添加URL去重
2. 添加智能超时
3. 添加进度显示
4. 测试验证

### 步骤5: 阶段4实施（监控统计）⚡

**预计时间**: 15分钟

1. 实现DownloadStats类
2. 集成到下载流程
3. 测试验证

### 步骤6: 完整测试 ✅

```bash
cd tests
python debug_download_test.py
```

**验证项目**:
- ✅ 下载成功率不降低
- ✅ 下载速度提升明显
- ✅ 无Unpaywall API调用
- ✅ 并发控制正常
- ✅ 统计数据准确

---

## 📊 预期效果对比

### 性能对比

| 指标 | 当前 | 升级后 | 改善 |
|------|------|--------|------|
| **并发数** | 3 | 15 | +400% |
| **下载总耗时** | 380秒 | 120-150秒 | -60% |
| **总流程耗时** | 450秒 | 200-250秒 | -50% |
| **平均下载速度** | 3.96秒/篇 | 1.5-2秒/篇 | +100% |
| **Unpaywall调用** | 98次 | 0次 | -100% |
| **成功率** | 31% | 31% | 保持不变 |

### 资源使用

| 资源 | 当前 | 升级后 | 说明 |
|------|------|--------|------|
| CPU | 低 | 中 | 并发增加，CPU使用提升 |
| 内存 | 低 | 中低 | 连接池占用少量内存 |
| 网络带宽 | 低 | 中高 | 并发下载，带宽利用率提升 |
| API调用 | 98次 | 0次 | 移除Unpaywall |

---

## ⚠️ 风险评估

### 高并发风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 被服务器限流 | 下载失败增加 | ✅ 每域名并发限制为5 |
| 网络拥塞 | 下载速度不稳定 | ✅ 连接池 + 智能重试 |
| 内存占用增加 | 系统资源紧张 | ✅ 流式下载，限制最大文件 |
| CPU负载增加 | 影响其他任务 | ✅ 可配置并发数 |

### 建议的并发数配置

| 环境 | 推荐并发数 | 说明 |
|------|-----------|------|
| **开发测试** | 10 | 平衡速度和稳定性 |
| **生产环境** | 15 | 推荐配置 |
| **高性能服务器** | 20 | 网络和CPU充足时 |
| **低配置机器** | 5 | 避免资源不足 |

---

## 🧪 测试计划

### 单元测试

```python
# tests/test_download_optimized.py

def test_url_deduplication():
    """测试URL去重"""
    pass

def test_domain_concurrency_limit():
    """测试域名并发限制"""
    pass

def test_connection_pool():
    """测试连接池"""
    pass
```

### 集成测试

```bash
# 小规模测试（10篇）
python tests/quick_test.py --query "test" --limit 10

# 中规模测试（50篇）
python tests/quick_test.py --query "graphene" --limit 50

# 完整测试（100篇）
python tests/debug_download_test.py
```

### 性能测试

**测试场景**:
1. 不同并发数对比（5, 10, 15, 20）
2. 不同网络环境（校园网、家庭网络、服务器）
3. 长时间运行稳定性（下载500+篇）

---

## 📝 配置建议

### 推荐配置（生产环境）

```python
# configs/constants.py

# ========== 论文下载 - 优化配置 ==========
DOWNLOAD_DIR = "./data/papers"
DOWNLOAD_TIMEOUT = 45                      # 增加超时
DOWNLOAD_MAX_RETRIES = 2                   # 保持不变
DOWNLOAD_MAX_CONCURRENT = 15               # 高并发
DOWNLOAD_RATE_LIMIT_PER_DOMAIN = 5        # 域名限制
DOWNLOAD_CONNECTION_POOL_SIZE = 20        # 连接池
MIN_FILE_SIZE = 10 * 1024                 # 10KB
MAX_FILE_SIZE = 50 * 1024 * 1024          # 50MB

# 进度显示
DOWNLOAD_SHOW_PROGRESS = True             # 显示进度条
DOWNLOAD_VERBOSE = False                  # 详细日志（调试用）

# 统计报告
DOWNLOAD_ENABLE_STATS = True              # 启用统计
DOWNLOAD_SAVE_STATS = True                # 保存统计到文件
```

### 保守配置（测试环境）

```python
# 如果遇到限流或不稳定，使用保守配置
DOWNLOAD_MAX_CONCURRENT = 8
DOWNLOAD_RATE_LIMIT_PER_DOMAIN = 3
DOWNLOAD_TIMEOUT = 60
```

---

## 📚 相关文档

**需要更新的文档**:
1. ✅ `docs/PDF_URL_VS_OA_URL.md` - 更新waterfall策略说明
2. ✅ `test_results/UNPAYWALL_INTEGRATION_REPORT.md` - 添加移除说明
3. ✅ `README.md` - 更新配置说明

**需要创建的文档**:
1. ✅ `docs/DOWNLOAD_OPTIMIZATION.md` - 本文档
2. ⬜ `docs/PERFORMANCE_TUNING.md` - 性能调优指南
3. ⬜ `docs/TROUBLESHOOTING.md` - 常见问题排查

---

## 🎯 总结

### 关键改进

1. ✅ **移除Unpaywall** - 消除冗余，减少98次API调用
2. ✅ **15倍并发** - 从3提升到15，大幅提速
3. ✅ **连接池复用** - 减少TCP开销
4. ✅ **域名限流** - 防止被封禁
5. ✅ **智能去重** - 避免重复下载
6. ✅ **实时监控** - 统计分析

### 预期收益

- ⚡ **速度提升60%**: 380秒 → 120-150秒
- 💰 **成本降低**: 减少98次API调用
- 📊 **可观测性**: 详细统计和监控
- 🛡️ **稳定性**: 域名限流 + 智能重试

### 实施优先级

1. **立即实施**: 阶段1（移除Unpaywall）+ 阶段2（提高并发）
2. **后续优化**: 阶段3（智能策略）+ 阶段4（监控统计）

---

**下一步**: 开始实施阶段1和阶段2？
