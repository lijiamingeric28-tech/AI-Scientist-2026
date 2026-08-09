# CDS/VizieR 服务加固方案（2026-08-06）

> 背景：2026-08-06 实测中 CDS 系服务（SIMBAD TAP + VizieR）间歇性高负载，
> 同一查询有时 1.5s 返回、有时 46s read timeout；非 CDS 系（ADS/Unpaywall/arXiv）全程稳定。
> 调研结论：核心大表直连 ESA/NASA 官方档案、VizieR 多镜像轮询、本地缓存，
> 是绕开 CDS 单点故障的三个方向。

---

## 1. 当前服务端全景（改造前）

| 服务 | 端点 | 代码位置 |
|---|---|---|
| SIMBAD 解析（主） | `https://simbad.cds.unistra.fr/simbad/sim-tap/sync`（法国 CDS TAP） | property_standardization.py:90 |
| SIMBAD 解析（兜底） | astroquery `Simbad()` → 同域 legacy 接口 | property_standardization.py:116 |
| VizieR 星表查询 | `vizier.cfa.harvard.edu`（美国哈佛镜像） | config.yaml:22 + database_query.py:97 |
| 补充材料 J/ 表 | astroquery Vizier（默认哈佛镜像） | supplementary_query.py |
| CDS 表存在性验证 | `https://cdsarc.cds.unistra.fr/viz-bin/cat/` | supplementary_query.py:102 |
| ADS 论文检索 | `api.adsabs.harvard.edu` | ads_search.py |

**故障时间线（2026-08-06）**：
- 09:53 (Vega)：全部正常（SIMBAD 2s、VizieR 秒回）
- 11:28-11:47 (Betelgeuse)：SIMBAD TAP 持续 30s read timeout（重试 2 次仍失败）
- 11:47-11:51 (Betelgeuse)：VizieR 6/9 查询 Read timed out
- 12:10：SIMBAD 简单查询恢复 1.5s；完整 JOIN 查询仍 46s 超时
- ADS/Unpaywall/arXiv 全程稳定

---

## 2. 调研结论（2026-08，用户提供）

### 2.1 独立机构官方档案（优先级最高 🌟🌟🌟🌟🌟）

**ESA Gaia Archive**（`gea.esac.esa.int`）
- Gaia 科学观测 2025 年初结束，**2026-06 发布 DR4 预发布数据，2026-12 发布完整 DR4**
- 全球高频访问 ESA 接口，部分压力正来源于此
- TAP 服务免费、匿名、无需 API Key；同步查询限时 60s（单天体查询足够）
- 使用 `astroquery.gaia` 直连

**NASA IRSA**（`irsa.ipac.caltech.edu`）
- GIC 26-02 政策（2026-08-05 生效）仅针对基金申请人，公共数据 API 未关停
- 2MASS/WISE 免费开放、无需注册
- 建议 `astroquery.ipac.irsa` 的 `query_tap` 接口

### 2.2 VizieR 官方镜像列表

| 镜像 | 地区 | 说明 |
|---|---|---|
| `vizier.cds.unistra.fr` | 🇫🇷 法国主站 | 最全但易高负载 |
| `vizier.cfa.harvard.edu` | 🇺🇸 美国哈佛 | 当前默认，偶尔抽风 |
| `vizier.ast.cam.ac.uk` | 🇬🇧 英国剑桥 | |
| `vizier.nao.ac.jp` | 🇯🇵 日本国立天文台 | 亚洲区稳定 |

astroquery 0.4.12+ 支持 `VIZIER_SERVER` 全局替换。

### 2.3 TAPVizieR（ADQL 语法改写）

经典接口 URL 参数 → TAP ADQL：
```sql
-- 旧：https://vizier...?-source=I/239/hip_main&HIP=91262
-- 新：
SELECT Plx, pmRA, pmDE FROM "I/239/hip_main" WHERE HIP = 91262
```
工具：`pyvo` 或 `astroquery.utils.tap`。TAP 有独立并发队列池，比传统 CGI 抗压。

### 2.4 SQLite 缓存

- **Cache Key**：SIMBAD 主 ID（Main ID）+ 星表标识（Catalog ID）联合主键
  （不要用自然语言名字，别名太多）
- **TTL**：历史星表（Hipparcos/HR 等）数据静态，Gaia DR3 在 DR4 发布前也静态
  → 半年甚至永久有效
- 效果：查过的天体第二次 10ms 级秒回，极大降低外部 API 依赖

### 2.5 快速失败 / 熔断

- 当前最坏 `9 表 × 30s = 4.5 分钟` 死等，生产环境灾难性
- **熔断设计**：连续 2 个星表查询报 timeout → 熔断，跳过剩余 CDS 查询，
  返回"部分降级结果"或打标给下游提示"部分数据源当前离线"

---

## 3. 已实施（Step 1：VizieR 多镜像 fallback）

### 改动文件

| 文件 | 内容 |
|---|---|
| **新增** `astroquery_ai/subgraph2/utils/vizier_client.py` | 镜像轮询核心模块 |
| `database_query.py` | 27 星表查询走 `query_with_fallback` |
| `supplementary_query.py` | `get_catalogs` / `find_catalogs` 走 fallback |

### vizier_client.py 设计

```python
VIZIER_MIRRORS = [
    "vizier.cfa.harvard.edu",   # 美国哈佛（当前默认）
    "vizier.nao.ac.jp",         # 日本国立天文台
    "vizier.ast.cam.ac.uk",     # 英国剑桥
    "vizier.u-strasbg.fr",      # 法国主站
]
DEFAULT_TIMEOUT = 10            # 单次超时 10s（原 30s）
ATTEMPTS_PER_MIRROR = 1         # 每镜像尝试 1 次

def query_with_fallback(query_func, row_limit=10, timeout=10, mirrors=None):
    """带镜像 fallback 的 VizieR 查询。
    可重试异常（ReadTimeout/ConnectionError/socket.timeout）→ 切镜像；
    非可重试异常直接抛出。全部镜像失败抛最后异常。"""
```

### 行为变化

- 哈佛超时 → 自动切日本/剑桥镜像，不再 4.5 分钟死等
- 单表最坏耗时：4 镜像 × 10s = 40s（原 9 表 × 30s = 4.5 分钟）
- 非可重试错误直接抛出，不浪费镜像轮询

### 验证结果（2026-08-06 实测）

```
镜像列表: [哈佛, 日本, 剑桥, 法国]
超时判定: ReadTimeout→True, ConnectionError→True, socket.timeout→True, ValueError→False
真实查询 Hipparcos HIP=91262 (Vega): OK, 1 rows, 81 cols, Plx=128.930
```

---

## 4. 待实施（按优先级）

### 4.1 SQLite 缓存（下一步推荐）
- 表：`simbad_cache`（key=main_id, 存 TAP/fallback 结果）、`vizier_cache`（key=catalog+key_column+value, 存 astropy Table 序列化）
- TTL 半年/永久（历史星表静态数据）
- 位置：`astroquery_ai/subgraph2/data/cache.db`（.gitignore 已覆盖 subgraph2/data/）

### 4.2 ESA/IRSA 直连（大重构）
- catalog_config.json 增加 `provider` 字段：`vizier | esa | irsa`
- Gaia 类 → `astroquery.gaia`（TAP）
- 2MASS/WISE 类 → `astroquery.ipac.irsa`（query_tap）
- 新增统一查询适配器，database_query 按 provider 分发

### 4.3 熔断状态机
- 连续 2 表超时 → 跳过剩余 CDS 查询
- 结果打标 `data_sources_degraded: true` + 原因，下游可见

---

## 5. 测试指引

### 手动回归测试（Step 1 后）

```bash
cd E:\work\astroquery_final

# 1. 单元验证 fallback 模块
python -X utf8 -c "
from astroquery_ai.subgraph2.utils.vizier_client import query_with_fallback
r = query_with_fallback(
    lambda v: v.query_constraints(catalog='I/239/hip_main', **{'HIP': '91262'}),
    row_limit=5, timeout=10)
print('Plx =', r[0][0]['Plx'])   # 期望 ≈128.93
"

# 2. 端到端查询（Vega：验证 2MASS/HR 路）
python run.py "Vega 的视差和自行"

# 3. 端到端查询（Betelgeuse：验证多镜像切换后的数据库路）
python run.py "Betelgeuse 的 JHK 红外星等和视向速度"
```

### 观察点

- 日志出现 `[VizieR] vizier.cfa.harvard.edu 查询失败 ... → 切换镜像` = fallback 生效
- 数据库路不再 6/9 全超时；`successful_catalogs` 非空
- 单表查询耗时 ≤40s（4 镜像 × 10s 上界）
