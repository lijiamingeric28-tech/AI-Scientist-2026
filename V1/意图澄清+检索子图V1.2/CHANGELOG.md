# Changelog

All notable changes to this project will be documented in this file.

## [1.2.0] - 2026-07-14

### 🚀 重大改进

#### 下载系统全面升级
- **性能提升488%**: 下载速度从0.25篇/秒提升至1.47篇/秒
- **耗时减少83%**: 下载时间从380秒降至66秒
- **总流程优化71%**: 完整流程从450秒降至129秒
- **成功率提升**: 从31-35%提升至40.6%

### ✨ 新增功能

#### 高并发下载
- 并发数从3提升至15 (+400%)
- 双重信号量控制（全局并发 + 每域名限制）
- 每域名最大5个并发，防止服务器封禁
- HTTP连接池（20个连接）优化网络性能

#### 智能下载策略
- **URL去重**: 自动识别并跳过重复链接
- **实时进度条**: 使用tqdm显示下载进度
- **域名限流**: 防止单一服务器过载

#### 详细统计报告
- 成功/失败/跳过计数统计
- 按来源统计（pdf_url, oa_url）
- 按域名统计（Top 5成功域名）
- 下载速度和总耗时分析
- 文件大小统计

### 🔧 优化改进

#### 移除Unpaywall冗余
- 删除Unpaywall API调用（与oa_url重复率100%）
- 减少98次冗余API调用
- 节省约10秒调用时间
- Waterfall策略简化：pdf_url → oa_url → core

#### 代码质量提升
- 添加完整的类型注释
- 优化异常处理机制
- 完善日志记录
- 代码结构更清晰

### 📚 文档完善

#### 新增文档
- `docs/DOWNLOAD_OPTIMIZATION_PLAN.md` - 下载优化计划
- `docs/PDF_URL_VS_OA_URL.md` - 下载源详细说明
- `test_results/UNPAYWALL_INTEGRATION_REPORT.md` - Unpaywall集成分析
- `test_results/DOWNLOAD_UPGRADE_COMPLETE_REPORT.md` - 升级完成报告

#### 测试报告
- 完整的性能对比数据
- 详细的测试日志
- 代码备份（backups/download_v1/）

### 🐛 Bug修复

- 修复`validate_pdf_file`导入缺失问题
- 修复异步下载异常传播问题
- 优化超时处理机制

### ⚙️ 配置变更

```python
# 新增配置项
DOWNLOAD_MAX_CONCURRENT = 15               # 从3提升到15
DOWNLOAD_TIMEOUT = 45                      # 从30提升到45秒
DOWNLOAD_RATE_LIMIT_PER_DOMAIN = 5        # 新增：每域名并发限制
DOWNLOAD_CONNECTION_POOL_SIZE = 20        # 新增：HTTP连接池大小
DOWNLOAD_SHOW_PROGRESS = True             # 新增：显示进度条
DOWNLOAD_ENABLE_STATS = True              # 新增：启用统计
```

### 📊 性能数据（实测）

**测试场景**: 96篇论文下载

| 指标 | V1.1 | V1.2 | 改善 |
|------|------|------|------|
| 并发数 | 3 | 15 | +400% |
| 下载耗时 | 380秒 | 66秒 | -83% |
| 总流程耗时 | 450秒 | 129秒 | -71% |
| 平均速度 | 0.25篇/秒 | 1.47篇/秒 | +488% |
| 成功下载 | 30-34篇 | 39篇 | +15-30% |
| 成功率 | 31-35% | 40.6% | +5-10% |

### 🔄 破坏性变更

- 移除了Unpaywall下载源（数据已包含在oa_url中）
- 修改了`_download_papers_async`函数签名（新增stats参数）

### 📦 依赖变更

- 无新增外部依赖
- tqdm用于进度显示（可选，已包含在现有依赖中）

---

## [1.1.0] - 2026-07-13

### 初始版本
- 意图澄清子图
- 检索子图（查询扩展 → 搜索 → 引用扩展 → 过滤排序 → 下载）
- 多源下载支持（pdf_url, oa_url, unpaywall, core）
- HTML Fallback功能
- 基础并发下载（3并发）

---

## 如何升级

### 从V1.1升级到V1.2

1. **拉取最新代码**
   ```bash
   git pull origin main
   ```

2. **更新配置文件**（可选）
   ```bash
   # 配置文件位置：configs/constants.py
   # 新增配置项已有默认值，无需手动修改
   ```

3. **测试验证**
   ```bash
   cd tests
   python quick_test.py --query "your query"
   ```

### 配置调优

根据您的环境调整并发参数：

```python
# 保守配置（低配置机器）
DOWNLOAD_MAX_CONCURRENT = 8
DOWNLOAD_RATE_LIMIT_PER_DOMAIN = 3

# 推荐配置（生产环境）
DOWNLOAD_MAX_CONCURRENT = 15
DOWNLOAD_RATE_LIMIT_PER_DOMAIN = 5

# 激进配置（高性能服务器）
DOWNLOAD_MAX_CONCURRENT = 20
DOWNLOAD_RATE_LIMIT_PER_DOMAIN = 8
```

---

## 贡献者

- [@lijiamingeric](https://github.com/lijiamingeric) - 下载系统优化
- Claude (Anthropic) - 技术支持

---

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件
