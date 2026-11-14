import asyncio
from astroquery_ai.science.catalogs import VizierCatalogs


def test_metadata_directory_is_expanded_without_inventing_tables_or_object_matches():
    class HTTP:
        def __init__(self): self.calls=[]
        async def request(self,*args,**kwargs):
            self.calls.append(kwargs['params'])
            xml = ('<VOTABLE><RESOURCE name="SYNTHETIC/catalog" type="meta"><DESCRIPTION>metadata only</DESCRIPTION></RESOURCE></VOTABLE>'
                if '-words' in kwargs['params'] else '<VOTABLE><RESOURCE name="SYNTHETIC/catalog"><TABLE name="SYNTHETIC/catalog/data"><FIELD name="Name" datatype="char"/></TABLE></RESOURCE></VOTABLE>')
            return xml.encode(),{'elapsed_seconds':0}
    async def run():
        http=HTTP();catalog=VizierCatalogs(http)
        result=await catalog.discover('SYNTHETIC task',{'main_id':'SYNTHETIC target','aliases':['SYNTHETIC alias']},[],[])
        tables=[t for r in result for resource in r['parsed']['resources'] for t in resource['tables']]
        assert [t['table_id'] for t in tables]==['SYNTHETIC/catalog/data']
        assert tables[0]['rows']==[]
        assert sum(p.get('-source')=='SYNTHETIC/catalog' for p in http.calls)==1
        count=len(http.calls)
        cached=await catalog.discover('SYNTHETIC task',{'main_id':'SYNTHETIC target','aliases':['SYNTHETIC alias']},[],[],cached=result,active_seconds=0)
        assert len(http.calls)==count and len(cached)==len(result)
    asyncio.run(run())
