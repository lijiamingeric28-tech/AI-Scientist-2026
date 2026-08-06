"""
End-to-end Property Mapping System
Input: target name + property description -> SIMBAD -> otype -> RAG prompt -> Qwen API -> property list
"""
import json, os, sys, re, requests, xml.etree.ElementTree as ET, io
from pathlib import Path
from collections import defaultdict

# Windows UTF-8 fix
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Config
PROJECT_ROOT = Path(__file__).parent.parent
RAG_DIR = PROJECT_ROOT / "rag_properties"
MODEL = "qwen3.7-plus"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def load_api_key():
    k = os.getenv("DASHSCOPE_API_KEY", "")
    if not k:
        for ep in [PROJECT_ROOT / ".env", PROJECT_ROOT / "astroquery_ai" / ".env"]:
            if ep.exists():
                for line in ep.read_text(encoding='utf-8').splitlines():
                    if line.strip().startswith('DASHSCOPE_API_KEY='):
                        k = line.split('=', 1)[1].strip().strip('"').strip("'")
                        break
    return k

DASHSCOPE_API_KEY = load_api_key()

# SIMBAD query
def simbad_query(name):
    url = "http://simbad.cds.unistra.fr/simbad/sim-id"
    params = {"output.format": "VOTABLE", "Ident": name,
              "output.params": "main_id,otype,otypes,sp_type,coo(ICRS)"}
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return None, f"SIMBAD query failed: {e}"
    root = ET.fromstring(resp.content)
    ns = {'v': 'http://www.ivoa.net/xml/VOTable/v1.2'}
    info = root.find('.//v:INFO[@name="Error"]', ns)
    if info is not None and info.get('value'):
        return None, f"SIMBAD: {info.get('value')}"
    td = root.find('.//v:TABLEDATA', ns)
    if td is None: return None, "Empty result"
    rows = td.findall('v:TR', ns)
    if not rows: return None, f"Not found: {name}"
    tds = rows[0].findall('v:TD', ns)
    fields = [t.text.strip() if t.text else '' for t in tds]
    cols = [f.get('name','') for f in root.findall('.//v:FIELD', ns)]
    try: return dict(zip(cols, fields)) if len(cols)==len(fields) else {'raw':fields}, None
    except Exception as e: return None, f"Simbad parse error: {e}"


# otype -> filename
def load_rag(simbad_result):
    """Find the best RAG file from SIMBAD result. Uses OTYPES pipe-separated compact codes first, then OTYPE."""
    if not simbad_result: return None

    # Try OTYPES first (pipe-separated compact codes like 'QSO|AGN|BLL|...')
    otypes = simbad_result.get('OTYPES', '') or simbad_result.get('otypes', '')
    if otypes:
        for code in otypes.split('|'):
            code = code.strip()
            if not code: continue
            fname = code.replace('*','_star').replace('/','_').replace(' ','_') + '.json'
            fp = RAG_DIR / fname
            if fp.exists():
                try: return json.loads(fp.read_text(encoding='utf-8'))
                except: continue

    # Fallback: try OTYPE verbose
    otype = simbad_result.get('OTYPE', '') or simbad_result.get('otype', '')
    if otype:
        fname = otype.strip().replace('*','_star').replace('/','_').replace(' ','_') + '.json'
        fp = RAG_DIR / fname
        if fp.exists():
            try: return json.loads(fp.read_text(encoding='utf-8'))
            except: pass

    # Last fallback: generic star
    fp = RAG_DIR / '_star.json'
    if fp.exists():
        try: return json.loads(fp.read_text(encoding='utf-8'))
        except: pass
    return None

# Prompt builder
def build_prompt(rag, target_name):
    props = rag.get('properties', [])
    by_cat = defaultdict(list)
    for p in props: by_cat[p.get('category','other')].append(p)

    cat_names = {'photometry':'[Photometry]','spectroscopy':'[Spectroscopy]','physical':'[Physical]',
                 'astrometry':'[Astrometry]','variability':'[Variability]','classification':'[Classification]',
                 'environment':'[Environment]','identification':'[ID]'}

    parts = []
    for cat, plist in by_cat.items():
        parts.append(f"\n## {cat_names.get(cat,cat)}")
        for p in plist:
            parts.append(f"  [{p['property_id']}] {p['name_cn']} ({p.get('category','')}) - {p.get('description','')}")

    return f"""You are an astrophysics data query assistant.

## Target
Name: {target_name}
Type: {rag['otype']} ({rag.get('name_cn','')})
Description: {rag.get('description','')}

## Available Properties
Each line format: [property_id] ChineseName (category) - description

{chr(10).join(parts)}

## Task
Based on the user's request, select the most relevant properties from the list above.
Output JSON only:
{{
  "target": "{target_name}",
  "otype": "{rag['otype']}",
  "requested_properties": [
    {{"property_id": "...", "name_cn": "...", "reason": "one sentence why"}}
  ]
}}

Rules:
1. Only select from the listed properties; do NOT invent new ones
2. For broad requests (e.g. "radio properties"), include all relevant band properties
3. For vague requests (e.g. "basic parameters"), select the 10-15 most fundamental properties
4. Include error/uncertainty properties when precision matters
"""

# DashScope API call
def call_qwen(system_prompt, user_query):
    if not DASHSCOPE_API_KEY:
        return None, "DASHSCOPE_API_KEY not set"
    payload = {"model": MODEL, "messages": [
        {"role":"system","content":system_prompt},
        {"role":"user","content":user_query}
    ], "temperature": 0.1, "max_tokens": 4096}
    try:
        resp = requests.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            json=payload, headers={"Authorization":f"Bearer {DASHSCOPE_API_KEY}","Content-Type":"application/json"}, timeout=90)
        resp.raise_for_status()
        return resp.json(), None
    except Exception as e:
        return None, f"API failed: {e}"

# Main
def main():
    print("\n" + "=" * 60)
    print("  Property Mapping System")
    print("=" * 60)
    target = input("Target name (e.g. 3C 273, WR 1): ").strip()
    if not target: print("No target."); return
    query = input("Property description (e.g. radio and X-ray): ").strip()
    if not query: print("No query."); return

    print(f"\n[Query] {target} | {query}")
    print("-" * 60)

    print("[Step 1] SIMBAD...")
    sim, err = simbad_query(target)
    if err: print(f"FAIL: {err}"); return
    mid = sim.get('MAIN_ID','') or sim.get('main_id','?')
    otype_display = sim.get('OTYPE','') or sim.get('otype','?')
    print(f"  main_id={mid}  otype={otype_display}")

    print("[Step 2] Load RAG...")
    rag = load_rag(sim)
    if not rag:
        print("FAIL: no RAG data"); return
    print(f"  {rag['name_cn']} ({rag['otype']}) - {len(rag['properties'])} props")

    print(f"[Step 3] Qwen API ({MODEL})...")
    sp = build_prompt(rag, target)
    result, err = call_qwen(sp, query)
    if err: print(f"FAIL: {err}"); return

    content = result['choices'][0]['message']['content']
    tokens = result.get('usage',{}).get('total_tokens','?')
    print(f"  Done ({tokens} tokens)")

    # Parse JSON
    content = content.strip()
    content = re.sub(r'^```\w*\n','',content); content = re.sub(r'\n```$','',content)
    try: parsed = json.loads(content)
    except:
        m = re.search(r'\{[\s\S]*\}', content)
        if m:
            try: parsed = json.loads(m.group())
            except: print("JSON parse error. Raw:\n"+content); return
        else: print("No JSON found. Raw:\n"+content); return

    # Output
    props = parsed.get('requested_properties', [])
    print(f"\n{'='*60}")
    print(f"Results: {len(props)} properties for {target}")
    print(f"{'='*60}")
    for i, p in enumerate(props, 1):
        print(f"  {i:2d}. [{p['property_id']}] {p['name_cn']}")
        if p.get('reason'): print(f"      {p['reason']}")

    out = PROJECT_ROOT / f"output_{target.replace(' ','_')}.json"
    out.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nSaved: {out}")

if __name__ == "__main__":
    main()
