# 本次 GitHub 提交命令

从本机的 `AI-Scientist-2026` 仓库根目录执行。当前分支：`codex/knowledge-workbench`。远端 `origin` 已指向 `lijiamingeric28-tech/AI-Scientist-2026`，无需重新初始化或添加远端。

本次建议 **5 个 commit**。下面命令由维护者手动执行；整理过程没有暂存、提交、推送、合并或重写历史。

上传前请先轮换旧历史文档和集成测试曾保存的密钥：本次已脱敏文档并将旧测试改为从环境读取凭据，但该值已存在于 `origin/main` 的既有历史中，普通新提交无法清除历史记录。不要将本机 `.env`、运行数据库、缓存、下载原件或录屏目录强制加入 Git。

本地 `main` 与已有 `origin/main` 有分叉；以下只推送当前功能分支，不强制推送或覆盖 `main`。

## 准备

在 PowerShell 中按块执行；每次确认 Git 命令成功后再继续下一块。

```powershell
# 先进入你本机的 AI-Scientist-2026 仓库根目录
git branch --show-current
git status --short
git diff --cached --stat
```

预期分支为 `codex/knowledge-workbench`，暂存区为空。如果你之后又暂存了其他内容，先自行核对，不要把无关文件混入以下分组。

## Commit 1：仓库整理、文档更新与历史文档脱敏

```powershell
git add -- .gitignore AstroQuery/.gitignore README.md AstroQuery/README.md docs HISTORY_VERSION
git diff --cached --stat
git commit -m "chore(repo): prepare public repository and refresh application docs"
```

包括环境备份、测试输出和本地工作记录的忽略规则，当前应用与七样例说明、设计及性能文档、本文，以及历史文档和旧集成测试的密钥清理。

## Commit 2：后端工作台、科研流程与读取优化

```powershell
git add -- AstroQuery/backend AstroQuery/tests AstroQuery/tools/benchmarks ':(exclude)AstroQuery/tests/rebuild/test_demo_followups.py' ':(exclude)AstroQuery/tests/rebuild/test_demo_loading_speed.py'
git diff --cached --stat
git commit -m "feat(backend): integrate versioned workbenches and research reading"
```

包括知识类别与关联管理、规范草稿发布、自定义性质执行、固定知识依据、资料解读与对照、读索引及缓存、科研链路修正和对应后端测试。两个样例专项测试留到 Commit 4。

## Commit 3：前端阅读层次、知识与规范工作台、统一主题

```powershell
git add -- AstroQuery/frontend ':(exclude)AstroQuery/frontend/package.json' ':(exclude)AstroQuery/frontend/package-lock.json' ':(exclude)AstroQuery/frontend/public/demo-catalog.json' ':(exclude)AstroQuery/frontend/tests/demo*.test.mjs' ':(exclude)AstroQuery/frontend/src/components/chat/AggregatedReviewCard.jsx'
git diff --cached --stat
git commit -m "feat(frontend): organize research reading and themed workbenches"
```

包括四个结果入口、单篇解读与性质对照分离、准确统计、知识引用抽屉、工作台管理、按需加载、流动输入框、系统配色和对应前端测试。演示依赖、目录、专项测试及审核定位标记留到后续提交。

## Commit 4：最新 SN 2014J 样例与已保存追问

```powershell
git add -- AstroQuery/resources/demos AstroQuery/frontend/public/demo-catalog.json AstroQuery/tests/rebuild/test_demo_followups.py AstroQuery/tests/rebuild/test_demo_loading_speed.py
git diff --cached --stat
git commit -m "feat(demos): publish latest SN 2014J sample with saved follow-up"
```

包括约 27.2 MiB 的新压缩样例、发布索引、首位展示与已有真实追问，以及导入和追问兼容测试。旧六个样例没有改写；不上传实际运行数据库和原件缓存。

## Commit 5：原生内嵌窗口 V2 自动演示

```powershell
git add -- AstroQuery/tools/demo AstroQuery/frontend/package.json AstroQuery/frontend/package-lock.json 'AstroQuery/frontend/tests/demo*.test.mjs' AstroQuery/frontend/src/components/chat/AggregatedReviewCard.jsx
git diff --cached --stat
git commit -m "feat(demo): add native-window V2 guided application tour"
```

包括自动点击、逐屏节奏、审核准确定位与去重、黑色箭头与蓝色光晕、字幕时间轴、启动入口及专项回归。本地 `PROGRESS.md`、截图、浏览配置与彩排日志由忽略规则排除。

## 核对并上传当前分支

```powershell
git status --short
git log -5 --oneline
git push -u origin codex/knowledge-workbench
```

前两条确认预期文件均已提交、五个新提交齐全，再执行最后一条。没有 `--force`，没有自动合并 `main`。本次源码推送不创建 Release，也不会替换已有 Windows 安装包。
