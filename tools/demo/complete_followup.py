"""Complete only missing demo answer components, keeping the original version and blocks."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from astroquery_ai.runtime.repository import Repository
from astroquery_ai.runtime.storage import ArtifactStore
from astroquery_ai.runtime.delivery import DeliveryService
from astroquery_ai.runtime.history import History
from astroquery_ai.runtime.configuration import Configuration
from astroquery_ai.agent_harness import AgentController,AgentStore,load_task_bundle
from astroquery_ai.agent_harness.answer import answer_text
from astroquery_ai.agent_harness.controller import FORMAT_PROMPT
from prepare_followup import TASK

async def main():
    root=Path('runtime-data').resolve()
    app=SimpleNamespace(repository=Repository(root/'runtime.sqlite3'),configuration=Configuration(root))
    app.artifacts=ArtifactStore(root/'artifacts',app.repository)
    app.delivery=DeliveryService(app.repository,app.artifacts)
    app.history=History(app)
    store=AgentStore(app.repository)
    rows=store.get_messages(TASK)
    if any(r.get('request_id')=='sn2014j-demo-components-20261114-v1' and r['status']=='complete' for r in rows):
        print('Reusing completed components');return
    previous=next(r for r in rows if r.get('request_id')=='sn2014j-demo-ebv-followup-20261114-v1')
    bundle=load_task_bundle(TASK,app,previous['scope']['delivery_id'],previous['scope']['delivery_revision'],previous['scope']['snapshot_ref'])
    controller=AgentController(bundle,app)
    theory=controller.tools.execute_tool('get_scientific_theory',{'property_name':'prop-dot-r69b04-nt-sn-line-of-sight-ebv','theory_id':'common.photometry.color_extinction'})
    record=next(b for b in previous['answer']['blocks'] if b['type']=='table')['rows'][0]
    prompt=('只补充当前回答缺失的三个组件：简短的知识依据与示意试算说明 text、formula、explore。不要重复表格、误差图或方法对照。'
      '使用同一任务冻结知识中的 R_V=A_V/E(B-V) 的等价变形 A_V=R_V E(B-V)，引用完整 THEORY 标识；原文关系和本次示意试算须区分。'
      f'固定 E(B-V)={record["typed"]["value"]} mag，来自 [REC:{record["id"]}]；说明其原报误差与条件，不把试算当测量或采用值。'
      'explore 参数只有 R_V，name=Rv，min=1,max=5,step=0.1,value=3.1,choices=[]，'
      f'expression="Rv*{record["typed"]["value"]}"，x=Rv，y_label=A_V，y_unit=mag。'
      '标题包含“示意试算”；R_V=3.1 明确只是演示参数，不是 SN 2014J 的科学采用值。只返回 {"blocks":[...]}。')
    messages=[{'role':'system','content':'仅根据以下已冻结资料补充真实回答。\n'+theory+'\n测量：'+json.dumps(record,ensure_ascii=False)},
              {'role':'user','content':FORMAT_PROMPT+'\n'+prompt}]
    calls=[];blocks=[];citations={c['citation_id']:c for c in previous['citations']}
    output=Path('scratch/demo-tour-2026-11-14')
    (output/'component-input.json').write_text(json.dumps(messages,ensure_ascii=False,indent=2),encoding='utf-8')
    checkpoint=output/'generated-components.json'
    if checkpoint.exists():
        saved=json.loads(checkpoint.read_text(encoding='utf-8'))
        blocks=saved['blocks'];calls=saved['calls'];citations.update((c['citation_id'],c) for c in saved['citations'])
    else:
        project=controller.projection.block
        raw_blocks={}
        def capture(raw,index):
            raw_blocks[str(index)]=raw
            (output/'raw-components.json').write_text(json.dumps(raw_blocks,ensure_ascii=False,indent=2),encoding='utf-8')
            return project(raw,index)
        controller.projection.block=capture
        try:
            async for block,found in controller._generate(controller._get_client(),messages,calls):
                blocks=[b for b in blocks if b['id']!=block['id']]+[block]
                citations.update((c['citation_id'],c) for c in found)
        finally:
            checkpoint.write_text(json.dumps({'blocks':blocks,'calls':calls,'citations':list(citations.values())},ensure_ascii=False,indent=2),encoding='utf-8')
    if not {'formula','explore'} <= {b['type'] for b in blocks}:raise RuntimeError('Missing valid generated components; not publishing')
    if not any(c['type']=='theory' for c in citations.values()):raise RuntimeError('No grounded frozen knowledge citation')
    base=previous['answer']['blocks']
    for i,b in enumerate(blocks,len(base)+1):b['id']=f'b{i}'
    message,question,history,_=store.start(TASK,bundle.scope,'','sn2014j-demo-components-20261114-v1',{},retry_of=previous['id'])
    all_blocks=base+blocks
    store.save(TASK,message['id'],content=answer_text(all_blocks),blocks=all_blocks,citations=list(citations.values()),
               trace=previous['thought_steps'],status='complete',model=previous.get('model'),
               model_calls=(previous.get('model_calls') or [])+calls,fallback=False)
    (output/'component-receipt.json').write_text(json.dumps({'message_id':message['id'],'reused_answer':previous['id'],
      'calls':calls,'blocks':[b['type'] for b in all_blocks]},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'answer_id':message['id'],'blocks':[b['type'] for b in all_blocks],'citations':len(citations)}),flush=True)

if __name__=='__main__':asyncio.run(main())
