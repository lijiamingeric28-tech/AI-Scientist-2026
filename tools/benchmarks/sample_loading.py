"""Offline real sample import/UI API timings; uses disposable data, never live providers."""
import argparse,hashlib,json,math,os,pickle,statistics,sys,tempfile,time
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[2]);p.add_argument('--output',type=Path,required=True);p.add_argument('--samples',type=int,default=30);p.add_argument('--only');p.add_argument('--dump',type=Path);a=p.parse_args()
 source=a.source.resolve();sys.path.insert(0,str(source/'backend/src'))
 from astroquery_ai.runtime.configuration import EDITABLE
 os.environ.update({name.upper():'' for name in EDITABLE})
 from astroquery_ai.application.service import Application
 from astroquery_ai.api.http import create_app
 from astroquery_ai.runtime.codec import digest
 from fastapi.testclient import TestClient
 catalog=json.loads((source/'frontend/public/demo-catalog.json').read_bytes())['samples']
 if a.only:catalog=[item for item in catalog if item['task_id']==a.only]
 report={'source':str(source),'samples':a.samples,'cases':[]}
 with tempfile.TemporaryDirectory(prefix='aq-sample-speed-') as name:
  root=Path(name).resolve();assert root.parent==Path(tempfile.gettempdir()).resolve() and root.name.startswith('aq-sample-speed-')
  application=Application(root,allow_synthetic=True)
  decodes=[0];original_object=application.repository.object
  def observed_object(conn,task_id,kind,object_id,version=None):
   if kind=='delivery':decodes[0]+=1
   return original_object(conn,task_id,kind,object_id,version)
  application.repository.object=observed_object
  with TestClient(create_app(root,application=application,start_worker=False)) as client:
   def read(path):
    start=time.perf_counter();r=client.get(path);r.raise_for_status();return r.json(),(time.perf_counter()-start)*1000,len(r.content)
   for sample in catalog:
    tid=sample['task_id'];prefix=f'/api/tasks/{tid}';did=sample['delivery_id'];rev=sample['delivery_revision'];base=f'{prefix}/deliveries/{did}';pin=f'delivery_revision={rev}&expected_delivery_revision={rev}'
    state,first,_=read(prefix+'/state?view=workspace')
    paths={'head':prefix+f'/delivery?delivery_id={did}&delivery_revision={rev}', 'materials':base+f'/materials?view=workbench&candidates_only=true&limit=20&offset=0&{pin}'}
    head,head_ms,_=read(paths['head']);listing,list_ms,_=read(paths['materials'])
    probes={'state':state,'head':head,'materials':listing};first_reads={'workspace_import_ms':first,'head_ms':head_ms,'materials_ms':list_ms}
    if listing['items']:
     entry=listing['items'][0];pid=entry.get('property_id') or listing.get('selected_property_id');mid=entry['group_id'];suffix=f'material_id={mid}&property_id={pid}&view=workbench&{pin}'
     detail,_,_=read(base+'/materials?'+suffix);probes['material_detail']=detail
     records,_,_=read(base+'/material_records?'+suffix+'&limit=20&offset=0');probes['material_records']=records
     figures,_,_=read(base+'/material_figures?'+suffix+'&limit=12&offset=0');probes['material_figures']=figures
     if records.get('items'):
      record=records['items'][0];rid=record.get('record_id') or record.get('source',{}).get('measurement_id') or record.get('measurement_id')
      if rid:probes['record_detail']=read(base+f'/records?record_id={rid}&{pin}')[0]
      sid=record.get('source_id')
      if sid:probes['source_detail']=read(base+f'/sources?source_id={sid}&{pin}')[0]
     if figures.get('items'):probes['figure_detail']=read(base+f'/figures?figure_id={figures["items"][0]["figure_id"]}&{pin}')[0]
    fingerprints={key:digest(value) for key,value in probes.items()}
    if a.dump:a.dump.write_text(json.dumps(probes,ensure_ascii=False),encoding='utf-8')
    # Compare scientific row identity and payload bytes, excluding the importer-created origin timestamp.
    rows_hash=hashlib.sha256()
    with application.repository.read() as c:
     counts={}
     for table,order in [('tasks','task_id'),('objects','kind,object_id,version'),('events','seq'),('jobs','job_id')]:
      rows=c.execute(f'SELECT * FROM {table} WHERE task_id=?'+(" AND kind<>'task_origin'" if table=='objects' else '')+f' ORDER BY {order}',(tid,));count=0
      for row in rows:rows_hash.update(pickle.dumps(tuple(row),protocol=4));count+=1
      counts[table]=count
    warm={}
    if tid==a.only or tid=='827c01d6-0a9a-4e3e-bba8-db6a3aa3f5b5':
     for key,path in paths.items():
      times=[];sizes=[];decode_start=decodes[0]
      for _ in range(a.samples):
       value,ms,size=read(path);assert digest(value)==fingerprints[key];times.append(ms);sizes.append(size)
      times.sort();warm[key]={'p50_ms':statistics.median(times),'p95_ms':times[math.ceil(.95*len(times))-1],'bytes':sizes[0],'delivery_decodes':decodes[0]-decode_start}
    case={'id':tid,'name':sample['name'],'first_ms':first_reads,'fingerprints':fingerprints,'authoritative_rows_sha256':rows_hash.hexdigest(),'counts':counts,'warm':warm};report['cases'].append(case)
    print(json.dumps({'id':tid,'first_ms':first_reads,'warm':warm}),flush=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print('Verified cases',len(report['cases']),flush=True)
if __name__=='__main__':main()
