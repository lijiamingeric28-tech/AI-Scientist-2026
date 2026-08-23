# 27 张星表"别名→正则→查表"机制审计与问题清单

> 目的：逐个核对每张 VizieR 表"用哪一列匹配 SIMBAD 别名、怎么匹配"，供专家确认。
> 发现问题：ocl 表已证实失效（key_column 列名不存在）；2mass/ngc/ic 疑似有格式不匹配风险。

---

## 一、完整机制（三步）

### Step 1：SIMBAD 解析，得到别名列表

`astroquery_ai/property_standardization.py::query_simbad` 用 TAP/ADQL 查 SIMBAD，返回目标天体的全部别名（`ids` 字段，`|` 分隔）。

例：昴星团（M45）的 ids 含：
```
M 45 | NAME Pleiades | OCl 421.0 | Cl Melotte 22 | [KPS2012] MWSC 0305 | ...
```

### Step 2：别名 → 正则提取星表标识符

`subgraphs/subgraph2/utils/database_utils.py::extract_catalog_ids`：
- 遍历每个 SIMBAD 别名
- 对每个别名，遍历 27 张表的 `pattern`（正则）
- pattern 命中 → 提取 `group(1)` 作为该表的 `catalog_id`
- 同一表同一 id 去重

```python
pattern = cat_info['pattern']               # 如 "OCl\\s+([\\d\\.]+)"
match = re.search(pattern, alias)
catalog_id = match.group(1).strip()         # 如 "421.0"
```

### Step 3：用 key_column 构造 VizieR 约束查询

`subgraphs/subgraph2/nodes/database_query.py`：
```python
query_with_fallback(lambda v: v.query_constraints(
    catalog=id_info['vizier_table'],       # 如 "B/ocl/clusters"
    **{id_info['key_column']: id_info['id']}   # 如 {"OCl": "421.0"}
))
```

即：**在源表里 `WHERE key_column = catalog_id`**。匹配是否成功，取决于：
1. `key_column` 是否是源表**真实存在的列名**
2. `catalog_id` 的**格式**（整数/浮点/带前缀字符串）是否与该列存的格式一致

### Step 4：列映射 + 构建记录

`column_mapper` 把命中的行各列映射到 PropertySpec 性质，`build_database_records` 生成 EAV 记录（含 provenance：db_table/key_column/key_value/raw_column/row_index）。

---

## 二、27 张表逐张核对

图例：✅ 设计合理（别名能提取且能匹配）/ ⚠️ 疑似风险（需专家确认列格式）/ 🔴 已证实失效

| # | 表 key | vizier_table | pattern 提取结果 | key_column | 源表该列格式 | 判断 |
|---|---|---|---|---|---|---|
| 1 | gaia_dr3 | I/355/gaiadr3 | `Gaia DR3 (\d+)` → 整数 | Source | 整数（如 5854013331201520640）| ✅ |
| 2 | gaia_dr2 | I/345/gaia2 | `Gaia DR2 (\d+)` → 整数 | Source | 整数 | ✅ |
| 3 | 2mass | II/246/out | `2MASS J([\d\+\-\.]+)` → **去掉 J 前缀** `18365633+3847012` | _2MASS | 疑存**带 J 前缀** `J18365633+3847012` | ⚠️ 需确认 |
| 4 | wise | II/328/allwise | `WISE[A]? (J[\d\+\-\.]+)` → **保留 J** `J...` | AllWISE | `J...` | ✅ |
| 5 | sdss | V/147/sdss12 | `SDSS (J[\d\+\-\.]+)` → 保留 J | SDSS12 | `J...` | ✅ |
| 6 | tic | IV/38/tic | `TIC\s+(\d+)` → 整数 | TIC | 整数 | ✅ |
| 7 | epic | IV/34/epic | `EPIC\s+(\d+)` → 整数 | ID | ID 列是否即 EPIC 编号？| ⚠️ 需确认 |
| 8 | hipparcos | I/239/hip_main | `HIP\s+(\d+)` → 整数 | HIP | 整数 | ✅ |
| 9 | hd | III/135A/catalog | `HD\s+(\d+)` → 整数 | HD | 整数 | ✅ |
| 10 | ngc | VII/118/ngc2000 | `NGC\s+(\d+)` → **纯数字** `6205` | Name | 疑存**带前缀** `"NGC 6205"` | ⚠️ 需确认 |
| 11 | ic | VII/118/ngc2000 | `IC\s+(\d+)` → 纯数字 | Name | 疑存 `"IC 4756"` | ⚠️ 需确认 |
| 12 | ugc | VII/26D/catalog | `UGC\s+(\d+)` → 整数 | UGC | UGC 列是否带前缀？| ⚠️ 需确认 |
| 13 | mwsc | J/A+A/558/A53/catalog | `MWSC\s+(\d+)` → 整数 | MWSC | 整数 | ✅ |
| 14 | ocl | B/ocl/clusters | `OCl\s+([\d\.]+)` → **带小数点** `421.0` | **OCl（列不存在）** | 实际列是 recno/Cluster | 🔴 已证实失效 |
| 15 | pgc | VII/237/pgc | `(?:PGC\|LEDA)\s+(\d+)` → 整数 | PGC | 整数 | ✅ |
| 16 | 2masx | VII/233/xsc | `2MASX J([\d\+\-\.]+)` → 保留 J | 2MASX | `J...` | ✅ |
| 17 | iras | II/125/main | `IRAS\s+([\d\+\-\.]+)` → `18352+3844` | IRAS | IRAS 列格式需确认 | ⚠️ 需确认 |
| 18 | abell | VII/110A | `ACO\s+(\d+)` → 整数 | ACO | 整数 | ✅ |
| 19 | bax | B/bax/bax | `BAX\s+([\d\.\+\-]+)` → 坐标串 | BAX | 需确认 | ⚠️ 需确认 |
| 20 | mcxc | J/A+A/534/A109/mcxc | `MCXC\s+(J[\d\+\-\.]+)` → 保留 J | MCXC | `J...` | ✅ |
| 21 | psz2 | J/A+A/594/A27 | `PSZ2\s+(G[\d\+\-\.]+)` → 保留 G | PSZ2 | `G...` | ✅ |
| 22 | nbgg | VII/145/groups | `NBGG\s+([\d\-]+)` → `12-34` | NBGG | 需确认 | ⚠️ 需确认 |
| 23 | ghcg | J/A+AS/100/47 | `GHCG\s+(\d+)` → 整数 | GHCG | 整数？| ⚠️ 需确认 |
| 24 | 3c | VIII/1A/3c | `\b3C\s+(\d+)` → 整数 | 3C | 整数 | ✅ |
| 25 | hr | V/50/catalog | `\bHR\s+(\d+)` → 整数 | HR | 整数 | ✅ |
| 26 | ucac | I/322A/out | `UCAC4\s+(\d+-\d+)` → `123-456789` | UCAC4 | `HHH-NNNNNN` | ✅ |
| 27 | fermi | IX/67 | `4FGL (J[\d\.]+[+-][\d\.]+)` → 保留 J | 4FGL | `J...` | ✅ |

---

## 三、问题分类

### 🔴 已证实失效：ocl（B/ocl/clusters）

- **现象**：昴星团查询返回全表前 60 行（Berkeley 58 / NGC 7801 / FSR 0459 等不同星团的距离 269~4365 pc 全被当昴星团）
- **根因**：`key_column = "OCl"` 但**该表没有 OCl 列**（实际列是 `recno`/`Cluster`/`recno` 等）。约束 `OCl=421.0` 被 astroquery 忽略 → 返回全表
- **别名不匹配的根本矛盾**：SIMBAD 别名是 `OCl 421.0`，但 Dias+ 表里根本没有 OCl 编号，只有 `recno`（流水号，无法从别名推导）和 `Cluster`（星团名，如 `Cl Melotte 22`，而 SIMBAD 别名里有 `Cl Melotte 22` 但这个 alias 不会被 `OCl\s+` pattern 捕获）
- **修复方向待专家定**：① pattern 改匹配 `Cluster` 列（`Cl Melotte 22` 等星团名）② 或把 ocl 从 27 表剔除/降级

### ⚠️ 疑似风险：pattern 提取格式 vs 源表列格式不一致

| 表 | 风险点 | 待确认 |
|---|---|---|
| 2mass | pattern 去掉 J 前缀，_2MASS 列疑存带 J 完整串 | _2MASS 列到底存 `J...` 还是 `...`？|
| ngc / ic | pattern 提取纯数字，Name 列疑存 `"NGC 6205"` 完整串 | Name 列是带前缀字符串还是纯数字？|
| epic | pattern 是 EPIC，key_column 是 ID | ID 列是否就是 EPIC 编号？|
| ugc / iras / bax / nbgg / ghcg | pattern 提取格式与列格式未逐一验证 | 各表 key_column 列的真实格式 |

---

## 四、给专家的核心问题

1. **ocl**：B/ocl/clusters（Dias+）没有 `OCl` 列，如何从 SIMBAD 别名定位到正确星团行？用 `Cluster` 列（星团名）匹配是否可行？还是应剔除该表？
2. **2mass**：`_2MASS` 列是否带 `J` 前缀？若带，pattern 应改为保留 J（`2MASS (J[\d\+\-\.]+)`）。
3. **ngc/ic**：`Name` 列是 `"NGC 6205"` 完整串还是纯数字 `6205`？若带前缀，pattern 应提取完整名。
4. **epic**：`ID` 列是否就是 EPIC 编号（`EPIC\s+(\d+)` 提取的整数能否直接匹配）？
5. **ugc/iras/bax/nbgg/ghcg**：各自 key_column 列的存储格式是什么？

> 验证方法（astroquery）：
> ```python
> from astroquery.vizier import Vizier
> v = Vizier(columns=['**'], row_limit=3)
> v.VIZIER_SERVER = 'vizier.cfa.harvard.edu'
> r = v.query_constraints(catalog='<vizier_table>', **{'<key_column>': '<catalog_id>'})
> # 看返回几行；或用 columns 列表确认列名是否存在
> ```
