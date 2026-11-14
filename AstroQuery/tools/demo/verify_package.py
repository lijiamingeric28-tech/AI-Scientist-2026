"""Offline round-trip and exact history preservation for the updated demonstration."""
import hashlib,json,lzma,time
from pathlib import Path
from types import SimpleNamespace
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.storage import ArtifactStore
from astroquery_ai.runtime.delivery import DeliveryService
from astroquery_ai.runtime.history import History
from astroquery_ai.runtime.published_demos import PublishedDemos
from astroquery_ai.agent_harness import AgentStore,GroundingVerifier,load_task_bundle
from prepare_followup import TASK

def history(path):
    h=hashlib.sha256();count=0
    with lzma.open(path,'rb') as stream:
        for line in stream:
            if line.startswith(b'["agent_messages",'):continue
            h.update(line);count+=1
    return {'lines':count,'sha256':h.hexdigest()}

def main():
    root=Path.cwd();out=root/'scratch/demo-tour-2026-11-14';before=out/'before-publication'
    original=history(before/(TASK+'.jsonl.xz'));updated=history(root/'resources/demos'/(TASK+'.jsonl.xz'))
    assert original==updated,'Authoritative history lines changed'
    old=json.loads((before/'index.json').read_bytes())['samples'];new=json.loads((root/'resources/demos/index.json').read_bytes())['samples']
    assert {k:v for k,v in old.items() if k!=TASK}=={k:v for k,v in new.items() if k!=TASK}
    assert old[TASK]['media']==new[TASK]['media']
    dest=out/'isolated-import';dest.mkdir(exist_ok=True)
    repo=Repository(dest/'runtime.sqlite3');app=SimpleNamespace(repository=repo)
    app.artifacts=ArtifactStore(dest/'artifacts',repo);app.delivery=DeliveryService(repo,app.artifacts);app.history=History(app)
    from astroquery_ai.application.material_analysis import MaterialAnalysisService
    app.material_analysis=MaterialAnalysisService(app)
    demos=PublishedDemos(app);demos.directory=root/'resources/demos';demos.index={TASK:new[TASK]}
    start=time.perf_counter();assert demos.open(TASK);seconds=time.perf_counter()-start
    messages=AgentStore(repo).get_messages(TASK);answer=messages[-1]
    assert answer['role']=='assistant' and answer['status']=='complete'
    assert {'table','chart','formula','explore'} <= {b['type'] for b in answer['answer']['blocks']}
    bundle=load_task_bundle(TASK,app,answer['scope']['delivery_id'],answer['scope']['delivery_revision'])
    verifier=GroundingVerifier(bundle)
    for citation in answer['citations']:
        assert verifier.resolve(citation['marker']),citation['marker']
    report={'history':updated,'old_six_unchanged':True,'media_unchanged':True,'fresh_import_seconds':seconds,
            'saved_messages':len(messages),'citations_resolved':len(answer['citations']),
            'blocks':[b['type'] for b in answer['answer']['blocks']]}
    (out/'package-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)
if __name__=='__main__':main()
