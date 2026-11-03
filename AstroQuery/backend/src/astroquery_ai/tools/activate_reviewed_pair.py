"""Atomically select an installed science/knowledge pair for new tasks."""
import argparse
from pathlib import Path
from astroquery_ai.application.service import Application
from astroquery_ai.runtime.codec import canonical,loads,utcnow
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.lifecycle import InstanceLock
from astroquery_ai.runtime.paths import data_root


def activate(app, registry_id, knowledge_id):
    science=app.registry.load(registry_id)
    with app.repository.read() as conn:
        row=conn.execute("SELECT content_sha256 FROM registry_releases WHERE release_id=? AND kind='knowledge'",(knowledge_id,)).fetchone()
    if not row:raise DomainError('KB_UNAVAILABLE','知识版本未安装',422)
    knowledge=app.knowledge.load({'id':knowledge_id,'version':1,'content_sha256':row[0]})
    science_ref={'id':registry_id,'version':1,'content_sha256':science['manifest']['content_sha256']}
    if knowledge['manifest']['registry_release_ref']!=science_ref:
        raise DomainError('KB_REGISTRY_BINDING','科学库与知识库不是同一接受版本',422)
    knowledge_ref={'id':knowledge_id,'version':1,'content_sha256':knowledge['manifest']['content_sha256']}
    with app.repository.transaction() as conn:
        if conn.execute("SELECT 1 FROM jobs WHERE status='running' LIMIT 1").fetchone():
            raise DomainError('RELEASE_SWITCH_BUSY','仍有运行作业，不能切换默认库',409)
        previous={row['key']:loads(row['payload']) for row in conn.execute(
            "SELECT key,payload FROM settings WHERE key IN ('active_registry','active_knowledge')")}
        for key,value in [('active_registry',{'release_id':registry_id,'content_sha256':science_ref['content_sha256']}),
                          ('active_knowledge',knowledge_ref)]:
            conn.execute('INSERT INTO settings VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,revision=revision+1',
                         (key,canonical(value).decode()))
    return {'activated_at':utcnow(),'previous':previous,'registry':science_ref,'knowledge':knowledge_ref,
            'old_task_references_rewritten':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime-root',type=Path)
    p.add_argument('--registry-release',required=True)
    p.add_argument('--knowledge-release',required=True)
    args=p.parse_args();root=data_root(args.runtime_root)
    with InstanceLock(root):
        result=activate(Application(root),args.registry_release,args.knowledge_release)
    print(canonical(result).decode())


if __name__=='__main__':main()
