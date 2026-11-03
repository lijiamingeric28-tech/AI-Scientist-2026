"""Read caches retain validation boundaries and independent caller data."""
from types import SimpleNamespace
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.science.knowledge import KnowledgeService


def test_author_cache_rechecks_changed_files_and_returns_independent_values(tmp_path,monkeypatch):
    manifest={'schema_version':'insight-knowledge/3','content_files':[{'path':'entries.json'}],
              'registry_release_ref':{'id':'synthetic','content_sha256':'expected'}}
    (tmp_path/'manifest.json').write_bytes(canonical(manifest));file=tmp_path/'entries.json';file.write_text('first')
    registry=SimpleNamespace(load=lambda _: {'manifest':{'content_sha256':'expected'}})
    service=KnowledgeService(tmp_path,None,registry);calls=[]
    def validate(directory):
        calls.append(directory);return {'values':[file.read_text()]}
    monkeypatch.setattr(service,'_validate',validate)
    first=service.validate(tmp_path);first['values'].append('caller mutation')
    assert service.validate(tmp_path)=={'values':['first']} and len(calls)==1
    file.write_text('second version')
    assert service.validate(tmp_path)=={'values':['second version']} and len(calls)==2
    manifest['another_field']='changed';(tmp_path/'manifest.json').write_bytes(canonical(manifest))
    service.validate(tmp_path);assert len(calls)==3


def test_settings_summary_reads_installed_manifest_without_running_scientific_consumers(tmp_path):
    from astroquery_ai.runtime.application import Application
    from astroquery_ai.runtime.codec import content_hash,utcnow
    from astroquery_ai.application.library_summary import installed_summary
    app=Application(tmp_path/'runtime',allow_synthetic=True)
    directory=tmp_path/'installed';directory.mkdir()
    manifest={'schema_version':'synthetic-summary','counts':{'entries':7,'otypes':3,'bindings':12}}
    manifest['content_sha256']=content_hash(manifest)
    (directory/'manifest.json').write_bytes(canonical(manifest))
    with app.repository.transaction() as c:
        c.execute('insert into registry_releases values(?,?,?,?,?,?)',('synthetic',manifest['content_sha256'],str(directory),'knowledge',1,utcnow()))
        c.execute('insert into settings values(?,?,1)',('active_knowledge',canonical({'id':'synthetic','content_sha256':manifest['content_sha256']})))
    summary=installed_summary(app)
    assert summary['knowledge_content']['entries']==7
    assert summary['knowledge_bindings']['verification_mode']=='installed_manifest'
    assert summary['registry']['state']=='unavailable'
    manifest['counts']['entries']=999;(directory/'manifest.json').write_bytes(canonical(manifest))
    assert installed_summary(app)['knowledge_bindings']['reason']=='manifest_changed'
