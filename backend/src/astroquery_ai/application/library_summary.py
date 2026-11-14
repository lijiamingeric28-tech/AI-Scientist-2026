"""Fast installed-library metadata for Settings; scientific use still validates content."""
from pathlib import Path
from astroquery_ai.runtime.codec import content_hash,loads


def installed_summary(app):
    def installed(key,kind):
        with app.repository.read() as c:
            row=c.execute('select payload from settings where key=?',(key,)).fetchone()
            if not row:return {'state':'unavailable','reason':'not_installed'}
            ref=loads(row[0]);identity=ref.get('release_id') or ref.get('id')
            release=c.execute('select * from registry_releases where release_id=? and kind=?',(identity,kind)).fetchone()
            if not release:return {'state':'unavailable','reason':'not_installed'}
            if c.execute('select 1 from revocations where release_id=?',(identity,)).fetchone():
                return {'state':'unavailable','reason':'revoked'}
        try:
            manifest=loads((Path(release['path'])/'manifest.json').read_bytes())
            if content_hash(manifest)!=ref['content_sha256'] or release['content_sha256']!=ref['content_sha256']:
                return {'state':'unavailable','reason':'manifest_changed'}
        except (OSError,ValueError,KeyError,TypeError):
            return {'state':'unavailable','reason':'manifest_unavailable'}
        return {'state':'available','release_id':identity,'content_sha256':ref['content_sha256'],
                'counts':manifest.get('counts',{}),'registry_ref':manifest.get('registry_release_ref'),
                'verification_mode':'installed_manifest'}
    registry=installed('active_registry','property');knowledge=installed('active_knowledge','knowledge')
    counts=knowledge.get('counts',{})
    return {'registry':registry,'knowledge_bindings':{**knowledge,'bindings':counts.get('bindings')},
            'knowledge_content':{'state':knowledge['state'],'entries':counts.get('entries'),'types':counts.get('otypes'),
                                 'verification_mode':'installed_manifest'},
            'runtime_profiles':{owner:app._profile_state(owner) for owner in ('M01','M03','M04','M06','M08','M11')}}
