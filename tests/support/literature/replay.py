"""Offline literature fixtures used by the retrieval regression suite."""
import hashlib
import sqlite3
from astroquery_ai.runtime.codec import digest, loads


class ExactPDFHTTP:
    def __init__(self,original,app,job):self.original,self.app,self.job=original,app,job
    def __getattr__(self,name):return getattr(self.original,name)
    async def request(self,tid,owner,service,method,url,**kwargs):
        wid=self.job.get('payload',{}).get('work_id')
        if owner=='M05' and method.upper()=='GET' and wid:
            key='http-response-'+digest({'owner':owner,'service':service,'method':method,'url':url,
                'arguments':{k:v for k,v in kwargs.items() if k not in {'timeout','connect_timeout','read_timeout','max_bytes','recover_unavailable_cache'}}})
            for root in (self.app.repository.path.parent,*getattr(self.app,'lab_pdf_cache_roots',[])):
                database=root/'runtime.sqlite3'
                with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as c:
                    candidates=c.execute("select task_id,payload from objects where kind='http_response_cache' and object_id=? order by created_at",(key,)).fetchall()
                    for source_task,payload in candidates:
                        cached=loads(payload);artifact=cached['artifact']
                        source=c.execute("select payload from objects where task_id=? and kind in ('source','prepared_source') and object_id=? order by version desc",(source_task,wid)).fetchall()
                        if not any(loads(s[0]).get('artifact',{}).get('sha256')==artifact['sha256']
                                   and loads(s[0]).get('identity',{}).get('state')=='verified' for s in source):continue
                        path=(root/'artifacts'/artifact['relative_path']).resolve()
                        if not path.is_relative_to((root/'artifacts').resolve()) or not path.is_file():continue
                        raw=path.read_bytes()
                        if not raw.startswith(b'%PDF-') or len(raw)>kwargs.get('max_bytes',16*1024**2) or hashlib.sha256(raw).hexdigest()!=artifact['sha256']:continue
                        body={'source_task_id':source_task,'source_data_root':str(root),
                            'source_artifact_sha256':artifact['sha256'],'request_cache_ref':key,
                            'same_exact_request':True,'fresh_network_response':False,'work_id':wid}
                        with self.app.repository.transaction() as conn:
                            self.app.repository.validate_lease(conn,self.job)
                            self.app.repository.put_object(conn,tid,'lab_http_reuse','reuse-'+digest([self.job['job_id'],key]),1,body)
                        return raw,{**cached['metadata'],**body,'lab_exact_pdf_cache':True}
        return await self.original.request(tid,owner,service,method,url,**kwargs)
