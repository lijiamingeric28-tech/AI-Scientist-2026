"""Independent-process full scientific validation timing and exact-output fingerprints."""
import argparse,json,math,os,statistics,subprocess,sys,time
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[2]);p.add_argument('--samples',type=int,default=5);p.add_argument('--output',type=Path);p.add_argument('--worker',action='store_true');a=p.parse_args()
 if a.worker:
  sys.path.insert(0,str(a.source.resolve()/'backend/src'))
  from astroquery_ai.registry.distribution import load_verified_distribution
  from astroquery_ai.runtime.codec import loads,digest
  directory=a.source.resolve()/'resources/property_registry/production';manifest=loads((directory/'manifest.json').read_bytes())
  started=time.perf_counter();result,_=load_verified_distribution(directory,manifest);elapsed=time.perf_counter()-started
  fingerprints={name:digest({str(k):v.model_dump(mode='json') if hasattr(v,'model_dump') else v for k,v in result[name].items()}) for name in ['context_bindings','composition_bindings','definition_views','profile_views','source_definition_refs']}
  print(json.dumps({'seconds':elapsed,'contexts':len(result['context_bindings']),'manifest':result['manifest'],'fingerprints':fingerprints}));return
 runs=[]
 for n in range(a.samples):
  env={**os.environ,'PYTHONUTF8':'1'}
  completed=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--source',str(a.source),'--worker'],capture_output=True,text=True,encoding='utf-8',env=env,check=True)
  item=json.loads(completed.stdout);runs.append(item);print('sample',n+1,round(item['seconds'],3),flush=True)
 assert all(r['manifest']==runs[0]['manifest'] and r['fingerprints']==runs[0]['fingerprints'] for r in runs)
 durations=sorted(r['seconds'] for r in runs);report={'source':str(a.source.resolve()),'samples':a.samples,'p50_seconds':statistics.median(durations),'p95_seconds':durations[math.ceil(.95*len(durations))-1],'runs':runs}
 if a.output:a.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if k!='runs'}),flush=True)
if __name__=='__main__':main()
