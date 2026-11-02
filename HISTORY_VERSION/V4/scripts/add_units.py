"""
批量为 RAG 性质库补充 standard_unit（一次性工具脚本）

用法::

    set DASHSCOPE_API_KEY=sk-xxx
    python add_units.py                    # 全量补全（跳过已有 unit 的性质）
    python add_units.py --dry-run          # 只生成清单，不写回 JSON
    python add_units.py --concurrency 32   # 调整并发数
    python add_units.py --only AGN QSO     # 只处理指定 otype 文件
    python add_units.py --force            # 重新生成已有 unit 的性质

机制：
  每个 otype 文件一次请求（整批性质一起问），高并发异步处理 100 个文件。
  模型只允许从白名单单位里选，保证与下游 unit_conversions 兼容。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

import httpx

# Windows 控制台 UTF-8
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).parent.parent
RAG_DIR = PROJECT_ROOT / "rag_properties"
MODEL = "qwen3.7-flash"
DEFAULT_DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
REPORT_PATH = PROJECT_ROOT / "unit_fill_report.json"

# ══════════════════════════════════════════════════════════════
# 允许的单位白名单
#
# 取自子图4 configs/schema_mapping.yaml 的 unit_conversions_astrophysics
# 各维度组键名。模型只能从这里选，否则下游 unit_converter 认不出来。
# 空串 "" 表示无量纲（红移、色指数、比值、标志位、名称等）。
# ══════════════════════════════════════════════════════════════

ALLOWED_UNITS = [
    "",  # 无量纲/分类/标识/比值/色指数
    # 距离
    "pc", "kpc", "Mpc", "Gpc", "AU", "ly",
    # 质量
    "Msun", "M_jup", "M_earth", "kg", "g",
    # 半径/尺寸
    "Rsun", "R_jup", "R_earth", "km", "m", "cm",
    # 光度/能量
    "erg/s", "Lsun", "W", "erg", "J", "eV", "keV", "MeV", "GeV", "TeV",
    # 速度
    "km/s", "m/s", "cm/s",
    # 自行
    "mas/yr", "arcsec/yr",
    # 周期/时间
    "d", "hr", "min", "s", "ms", "yr",
    # 年龄
    "Gyr", "Myr", "kyr",
    # 星等/消光
    "mag",
    # 温度
    "K",
    # 视差
    "mas", "arcsec",
    # 丰度/金属丰度/表面重力
    "dex",
    # 流量密度
    "Jy", "mJy", "uJy",
    # 色散量/旋转量
    "cm^-3 pc", "rad/m^2",
    # 频率
    "Hz", "kHz", "MHz", "GHz", "THz",
    # 磁场
    "G", "mG", "uG", "kG", "T",
    # 压强
    "Pa", "dyn/cm^2", "bar", "atm",
    # 密度
    "g/cm^3", "kg/m^3", "cm^-3",
    # 角度
    "deg", "arcmin",
    # 波长
    "nm", "Angstrom", "um", "mm",
    # 面亮度
    "mag/arcsec^2", "MJy/sr",
    # 百分比
    "%",
    # 等值宽度（谱线）
    "Angstrom",
    # 面密度
    "pc^-2",
    # 柱密度
    "cm^-2",
    # 流量（非密度）
    "erg/s/cm^2",
]
_ALLOWED_SET = set(ALLOWED_UNITS)
# ══════════════════════════════════════════════════════════════
# Prompt 构造：一个 otype 文件的所有性质一次问完
# ══════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """你是天文数据标准化专家。任务：为天体物理性质字段判定其标准单位。

## 规则
1. 只能从【允许单位表】里选一个，不得自造单位字符串。
2. 无量纲量填空串 ""：红移、色指数（B-V/BP-RP）、比值、指数、标志位(flag)、
   分类/光谱型、名称/ID、计数、概率、置信度、偏心率、质量比、轴比、
   金属丰度以外的相对丰度比([X/Fe] 用 dex)。
3. 对数量用其线性量的单位还是 dex，按天文惯例判断：
   - log g（表面重力）→ dex
   - [Fe/H]、[M/H]、[X/Fe] 等丰度 → dex
   - log L、log M 这类"对数化的物理量" → 仍填该物理量单位（如 erg/s、Msun）
4. 星等类（apparent/absolute magnitude、各波段 mag、消光 A_V、光变幅度）→ mag
5. 谱线等值宽度 EW → Angstrom；谱线宽度 FWHM 若以速度表示 → km/s
6. 角尺寸/角距/角半径 → arcsec（大尺度星系团用 arcmin 也可）
7. 色指数类性质→mag
7. 天体测量坐标（赤经/赤纬/银经/银纬）→ deg
8. 拿不准时，优先选该物理量在天文文献中最常用的单位。

## 输出
严格 JSON，不要任何解释文字或 markdown 围栏：
{"units": {"property_id": "单位", "property_id2": "", ...}}
必须为输入的每一个 property_id 都给出条目。"""


def build_user_prompt(otype: str, name_cn: str, props: list[dict]) -> str:
    """把一个 otype 的性质列表拼成提问。"""
    lines = []
    for p in props:
        pid = p.get("property_id", "")
        cn = p.get("name_cn", "")
        cat = p.get("category", "")
        ucd = p.get("ucd", "")
        desc = (p.get("description", "") or "")[:150]
        lines.append(f"- {pid} | {cn} | category={cat} | ucd={ucd} | {desc}")

    units_str = ", ".join(f'"{u}"' for u in ALLOWED_UNITS)

    return f"""## 天体类型
{otype} ({name_cn})

## 允许单位表（只能从中选择）
{units_str}

## 待判定性质（共 {len(props)} 个）
每行格式：property_id | 中文名 | category | ucd | 描述
{chr(10).join(lines)}

请为上述全部 {len(props)} 个 property_id 判定标准单位，输出 JSON。"""


def parse_units(content: str) -> dict[str, str]:
    """从模型回复里抽取 units 映射，容忍 markdown 围栏与多余文本。"""
    text = content.strip()
    text = re.sub(r"^```\w*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                data = json.loads(m.group())
            except json.JSONDecodeError:
                return {}
    if not isinstance(data, dict):
        return {}

    units = data.get("units", data)
    if not isinstance(units, dict):
        return {}
    return {str(k): ("" if v is None else str(v).strip()) for k, v in units.items()}
# ══════════════════════════════════════════════════════════════
# 异步请求：单文件一次调用，带重试与退避
# ══════════════════════════════════════════════════════════════

async def call_llm(
    client: httpx.AsyncClient,
    api_key: str,
    base_url: str,
    system_prompt: str,
    user_prompt: str,
    max_retries: int = 4,
) -> tuple[str | None, str | None]:
    """调用 Qwen（DashScope 百炼兼容模式），返回 (content, error)。"""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 16384,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = await client.post(base_url, json=payload, headers=headers)

            # 限流/服务端错误 → 退避重试
            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt < max_retries:
                    wait = min(2 ** attempt, 30)
                    await asyncio.sleep(wait)
                    continue
                return None, f"HTTP {resp.status_code} after {max_retries} tries"

            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"], None

        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt < max_retries:
                await asyncio.sleep(min(2 ** attempt, 30))
                continue
            return None, f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001
            return None, f"{type(exc).__name__}: {exc}"

    return None, "max retries exceeded"


async def process_file(
    path: Path,
    client: httpx.AsyncClient,
    api_key: str,
    base_url: str,
    sem: asyncio.Semaphore,
    force: bool,
    dry_run: bool,
    progress: dict,
) -> dict:
    """处理单个 otype 文件：补全其所有性质的 unit。"""
    result = {
        "file": path.name,
        "otype": None,
        "total": 0,
        "need_fill": 0,
        "filled": 0,
        "invalid_unit": [],
        "missing_from_llm": [],
        "error": None,
        # 实际判定结果 {property_id: unit}，供 --dry-run 审核
        "units": {},
    }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"read failed: {exc}"
        return result

    otype = data.get("otype", path.stem)
    result["otype"] = otype
    props = data.get("properties", []) or []
    result["total"] = len(props)

    # 用 _unit_filled 标记区分"没问过"与"问过且判定为无量纲(unit='')"，
    # 否则无量纲性质每次重跑都会被重复提问。
    targets = props if force else [p for p in props if not p.get("_unit_filled")]
    result["need_fill"] = len(targets)

    if not targets:
        progress["done"] += 1
        print(f"[{progress['done']}/{progress['total']}] {otype:12s} 跳过（已补全）")
        return result

    async with sem:
        content, err = await call_llm(
            client, api_key, base_url, _SYSTEM_PROMPT,
            build_user_prompt(otype, data.get("name_cn", ""), targets),
        )

    if err:
        result["error"] = err
        progress["done"] += 1
        print(f"[{progress['done']}/{progress['total']}] {otype:12s} ✗ {err}")
        return result

    units = parse_units(content or "")
    if not units:
        result["error"] = "unparseable LLM response"
        progress["done"] += 1
        print(f"[{progress['done']}/{progress['total']}] {otype:12s} ✗ 响应无法解析")
        return result

    for p in targets:
        pid = p.get("property_id", "")
        if pid not in units:
            result["missing_from_llm"].append(pid)
            continue
        unit = units[pid]
        if unit not in _ALLOWED_SET:
            result["invalid_unit"].append({"property_id": pid, "unit": unit})
            continue
        p["unit"] = unit
        p["_unit_filled"] = True
        result["filled"] += 1
        result["units"][pid] = unit

    if not dry_run and result["filled"]:
        try:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"write failed: {exc}"

    progress["done"] += 1
    flags = []
    if result["invalid_unit"]:
        flags.append(f"{len(result['invalid_unit'])} 个非法单位")
    if result["missing_from_llm"]:
        flags.append(f"{len(result['missing_from_llm'])} 个漏答")
    tail = ("  ⚠ " + ", ".join(flags)) if flags else ""
    print(
        f"[{progress['done']}/{progress['total']}] {otype:12s} "
        f"✓ {result['filled']}/{result['need_fill']}{tail}"
    )
    return result
# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════

def _env_or_dotenv(key: str, default: str = "") -> str:
    """从环境变量或项目根 .env 读取配置值（key 不存在时返回 default）。"""
    v = os.getenv(key, "").strip()
    if v:
        return v
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default


def load_api_key() -> str:
    """读取 DashScope API Key（环境变量或 .env 的 DASHSCOPE_API_KEY）。"""
    return _env_or_dotenv("DASHSCOPE_API_KEY")


def load_base_url() -> str:
    """读取 DashScope 百炼兼容模式端点，拼出 chat/completions URL。"""
    base = _env_or_dotenv("DASHSCOPE_BASE_URL", DEFAULT_DASHSCOPE_BASE)
    return base.rstrip("/") + "/chat/completions"


def parse_args():
    p = argparse.ArgumentParser(
        description="批量为 RAG 性质库补充 standard_unit（Qwen·DashScope 异步并发）",
    )
    p.add_argument("--concurrency", type=int, default=16,
                   help="并发请求数（默认 16）")
    p.add_argument("--dry-run", action="store_true",
                   help="只生成报告，不写回 JSON")
    p.add_argument("--force", action="store_true",
                   help="重新判定已补全的性质")
    p.add_argument("--only", nargs="*", default=None, metavar="OTYPE",
                   help="只处理指定文件名（不含 .json），如 --only AGN QSO")
    p.add_argument("--timeout", type=float, default=180.0,
                   help="单请求超时秒数（默认 180）")
    return p.parse_args()


async def main_async(args) -> int:
    api_key = load_api_key()
    if not api_key:
        print("错误：未找到 DASHSCOPE_API_KEY")
        print("  设置环境变量：set DASHSCOPE_API_KEY=sk-xxx")
        print(f"  或写入文件：  {PROJECT_ROOT / '.env'}")
        return 2
    base_url = load_base_url()

    if not RAG_DIR.exists():
        print(f"错误：RAG 目录不存在 {RAG_DIR}")
        return 2

    files = sorted(RAG_DIR.glob("*.json"))
    if args.only:
        wanted = {n.removesuffix(".json") for n in args.only}
        files = [f for f in files if f.stem in wanted]
    if not files:
        print("没有匹配的文件")
        return 1

    print("═" * 64)
    print(f"  RAG 单位补全 | 模型 {MODEL}")
    print(f"  文件数 {len(files)} | 并发 {args.concurrency}"
          f"{' | DRY-RUN' if args.dry_run else ''}"
          f"{' | FORCE' if args.force else ''}")
    print("═" * 64)

    sem = asyncio.Semaphore(args.concurrency)
    progress = {"done": 0, "total": len(files)}
    limits = httpx.Limits(
        max_connections=args.concurrency + 4,
        max_keepalive_connections=args.concurrency,
    )

    async with httpx.AsyncClient(timeout=args.timeout, limits=limits) as client:
        results = await asyncio.gather(*[
            process_file(f, client, api_key, base_url, sem,
                         args.force, args.dry_run, progress)
            for f in files
        ])

    # ── 汇总 ──
    total_props = sum(r["total"] for r in results)
    total_need = sum(r["need_fill"] for r in results)
    total_filled = sum(r["filled"] for r in results)
    invalid = [(r["otype"], iv) for r in results for iv in r["invalid_unit"]]
    missing = [(r["otype"], pid) for r in results for pid in r["missing_from_llm"]]
    errors = [(r["otype"], r["error"]) for r in results if r["error"]]

    print("═" * 64)
    print(f"  性质总数     : {total_props}")
    print(f"  待补全       : {total_need}")
    print(f"  成功补全     : {total_filled}")
    print(f"  非法单位     : {len(invalid)}")
    print(f"  模型漏答     : {len(missing)}")
    print(f"  文件级错误   : {len(errors)}")
    print("═" * 64)

    if errors:
        print("\n失败文件（可重跑，已补全的会自动跳过）：")
        for ot, err in errors[:20]:
            print(f"  - {ot}: {err}")
        if len(errors) > 20:
            print(f"  ... 另有 {len(errors) - 20} 个")

    if invalid:
        print("\n非法单位（模型给了白名单外的值，未写入）：")
        for ot, iv in invalid[:20]:
            print(f"  - [{ot}] {iv['property_id']} → {iv['unit']!r}")
        if len(invalid) > 20:
            print(f"  ... 另有 {len(invalid) - 20} 个")

    if missing:
        print("\n模型漏答（未写入，重跑可补）：")
        for ot, pid in missing[:20]:
            print(f"  - [{ot}] {pid}")
        if len(missing) > 20:
            print(f"  ... 另有 {len(missing) - 20} 个")

    # DRY-RUN 或小批量时打印判定明细，便于人工审核
    if args.dry_run or len(files) <= 3:
        print("\n判定明细：")
        for r in results:
            if not r["units"]:
                continue
            print(f"\n── {r['otype']} ({r['file']}) ──")
            for pid, unit in r["units"].items():
                shown = unit if unit else "(无量纲)"
                print(f"  {pid:34s} → {shown}")

    report = {
        "model": MODEL,
        "dry_run": args.dry_run,
        "force": args.force,
        "summary": {
            "files": len(files),
            "total_properties": total_props,
            "need_fill": total_need,
            "filled": total_filled,
            "invalid_unit": len(invalid),
            "missing_from_llm": len(missing),
            "errors": len(errors),
        },
        "invalid_unit": [{"otype": o, **iv} for o, iv in invalid],
        "missing_from_llm": [{"otype": o, "property_id": p} for o, p in missing],
        "errors": [{"otype": o, "error": e} for o, e in errors],
        "per_file": results,
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n报告已写入: {REPORT_PATH}")
    if args.dry_run:
        print("DRY-RUN：未修改任何 RAG 文件")

    return 0 if not errors else 1


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\n已中断（已写入的文件保持不变，重跑会跳过已补全项）")
        return 130


if __name__ == "__main__":
    sys.exit(main())
