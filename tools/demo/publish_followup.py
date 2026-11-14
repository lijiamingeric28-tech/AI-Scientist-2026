"""Publish the approved saved conversation while preserving every other archive line."""
import hashlib,json,os,sqlite3
from pathlib import Path
from astroquery_ai.tools.pack_demos import append_followups
from prepare_followup import TASK

def main():
    root=Path.cwd();dest=root/'resources/demos';out=root/'scratch/demo-tour-2026-11-14/pack'
    out.mkdir(parents=True,exist_ok=True)
    catalog_path=root/'frontend/public/demo-catalog.json'
    catalog=json.loads(catalog_path.read_bytes());sample=next(s for s in catalog['samples'] if s['task_id']==TASK)
    index_path=dest/'index.json';index=json.loads(index_path.read_bytes())
    backup=root/'scratch/demo-tour-2026-11-14/before-publication';backup.mkdir(exist_ok=True)
    for p in (catalog_path,index_path):
        target=backup/p.name
        if not target.exists():target.write_bytes(p.read_bytes())
    original=dest/(TASK+'.jsonl.xz')
    if not (backup/original.name).exists():
        import shutil
        shutil.copy2(original,backup/original.name)
    with sqlite3.connect((root/'runtime-data/runtime.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        index['samples'][TASK]=append_followups(db,sample,original,index['samples'][TASK],out)
    os.replace(out/original.name,original)
    index_path.write_text(json.dumps(index,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
    sample['followup_count']=1
    sample['summary']='47 个资料性质解读范围与 4 项性质综合对照；960 条测量、52 幅图像，含真实科研追问、知识引用和交互试算。'
    catalog_path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'task_id':TASK,'messages':len(index['samples'][TASK]['public_messages']),
                      'archive_sha256':index['samples'][TASK]['sha256']}))
if __name__=='__main__':main()
