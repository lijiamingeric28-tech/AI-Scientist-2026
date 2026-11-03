"""Install immutable, evidenced model qualifications without importing science runs."""
import argparse
from pathlib import Path
import sqlite3

from astroquery_ai.application.service import Application
from astroquery_ai.runtime.codec import canonical, content_hash, loads, utcnow
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.lifecycle import InstanceLock


def install(app, source_database, owner):
    source_database = Path(source_database).resolve()
    if source_database == app.repository.path:
        raise DomainError('PROFILE_IMPORT_SOURCE', 'Source must be a separate qualification database')
    with sqlite3.connect(source_database.as_uri()+'?mode=ro', uri=True) as source:
        source.row_factory = sqlite3.Row
        incoming, reference = app.profile_authority.load(source, owner)
        setting = loads(source.execute('SELECT payload FROM settings WHERE key=?', ('profile:'+owner,)).fetchone()[0])
        with app.repository.transaction() as target:
            if target.execute("SELECT 1 FROM jobs WHERE status='running' LIMIT 1").fetchone():
                raise DomainError('PROFILE_IMPORT_BUSY', 'Stop active jobs before publishing qualifications', 409)
            previous, old_reference = app.profile_authority.load(target, owner, check_connection=False)
            if incoming['scope'] != previous['scope']:
                raise DomainError('PROFILE_IMPORT_SCOPE', 'Publication cannot expand scientific scope')
            old_executions = previous.get('execution_profiles', [previous.get('execution')])
            new_executions = incoming.get('execution_profiles', [incoming.get('execution')])
            if any(e not in new_executions for e in old_executions):
                raise DomainError('PROFILE_IMPORT_EXECUTION', 'Existing qualified executions must be preserved')
            refs = [dict(reference, kind='profile_validation')] + incoming['validation_evidence_refs']
            copied = []
            for ref in refs:
                task = app.repository.task(source, ref['task_id'])
                if task['kind'] != 'validation':
                    raise DomainError('PROFILE_IMPORT_TASK', 'Only validation evidence may be imported')
                row = source.execute('SELECT * FROM objects WHERE task_id=? AND kind=? AND object_id=? AND version=?',
                    (ref['task_id'], ref['kind'], ref['id'], ref['version'])).fetchone()
                if row is None or content_hash(loads(row['payload'])) != ref['content_sha256']:
                    raise DomainError('PROFILE_IMPORT_HASH', 'Qualification evidence hash mismatch')
                existing = target.execute('SELECT payload FROM objects WHERE task_id=? AND kind=? AND object_id=? AND version=?',
                    (ref['task_id'], ref['kind'], ref['id'], ref['version'])).fetchone()
                if existing:
                    if content_hash(loads(existing[0])) != ref['content_sha256']:
                        raise DomainError('PROFILE_IMPORT_CONFLICT', 'Existing immutable evidence differs')
                    continue
                if not target.execute('SELECT 1 FROM tasks WHERE task_id=?', (task['task_id'],)).fetchone():
                    columns=list(task)
                    target.execute('INSERT INTO tasks ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',
                        [task[k] for k in columns])
                elif app.repository.task(target, task['task_id'])['kind'] != 'validation':
                    raise DomainError('PROFILE_IMPORT_CONFLICT', 'Evidence task identity differs')
                columns=row.keys()
                target.execute('INSERT INTO objects ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')', tuple(row))
                copied.append(ref)
            target.execute('UPDATE settings SET payload=?,revision=revision+1 WHERE key=?',
                (canonical(setting).decode(), 'profile:'+owner))
            app.profile_authority.load(target, owner)
    return {'installed_at':utcnow(),'owner':owner,'validation_ref':reference,'previous_ref':old_reference,
            'copied_evidence_refs':copied,'scientific_scope_unchanged':True,
            'imported_scientific_runs':False,'source_database':str(source_database)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--source-database', type=Path, required=True)
    parser.add_argument('--owner', required=True)
    args=parser.parse_args()
    with InstanceLock(args.runtime_root):
        receipt=install(Application(args.runtime_root), args.source_database, args.owner)
    print(canonical(receipt).decode())


if __name__=='__main__':main()
