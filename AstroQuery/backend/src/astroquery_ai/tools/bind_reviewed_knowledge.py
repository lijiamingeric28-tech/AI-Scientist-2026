"""Bind supplied exact claim plans to the active reviewed registry."""
import argparse
from hashlib import sha256
from pathlib import Path
from astroquery_ai.application.service import Application
from astroquery_ai.runtime.codec import canonical, digest, loads
from astroquery_ai.runtime.paths import data_root
from astroquery_ai.runtime.lifecycle import InstanceLock
from astroquery_ai.registry.candidate import local_file
from astroquery_ai.registry.knowledge_bindings import bind_claim_plan, review_binding
from astroquery_ai.science.knowledge_content import KnowledgeContent
from astroquery_ai.science.bound_knowledge import package_content
from astroquery_ai.registry.projection import definition_view
from astroquery_ai.registry.amendments import reference_key


def build(app, plans, destination, *, registry_release=None, base_app=None):
    registry = app.registry.load(registry_release)
    registry_ref = {'id': registry['manifest']['release_id'], 'version': 1, 'content_sha256': registry['manifest']['content_sha256']}
    base_app=base_app or app
    with base_app.repository.read() as conn:
        current = loads(conn.execute("SELECT payload FROM settings WHERE key='active_knowledge'").fetchone()[0])
        base_path = Path(conn.execute('SELECT path FROM registry_releases WHERE release_id=?', (current['id'],)).fetchone()[0])
    original = base_app.knowledge.load(current)
    old_registry=base_app.registry.load(original['manifest']['registry_release_ref']['id'])
    content = KnowledgeContent().load(base_path / 'origin')
    bindings, reviews, gaps = [], [], []
    for old in original['data']['bindings']:
        # Existing exact definitions remain; moving their registry reference is
        # a new binding receipt, not a rewrite of original knowledge content.
        mapped=[]
        for p in old['property_bindings']:
            d=definition_view(registry,p['property_id'],p['definition_version'],p['definition_hash'])
            if d is None:
                old_choices=[b for (t,_),bs in old_registry['context_bindings'].items() if t in old['otype_scope']
                    for b in bs if b['property_id']==p['property_id'] and b['definition']['content_sha256']==p['definition_hash']]
                choices=[]
                for (t,_),bs in registry['context_bindings'].items():
                    if t not in old['otype_scope']:continue
                    for b in bs:
                        if b['property_id']!=p['property_id']:continue
                        receipt=b['candidate_projection_receipt']
                        if any(all(reference_key(receipt[k])==reference_key(ob['candidate_projection_receipt'][k])
                            for k in ('source_definition_ref','source_profile_ref')) for ob in old_choices):
                            choices.append(b)
                choices={ (b['definition']['content_sha256'],b['output_profile']['content_sha256']):b for b in choices }
                if len(choices)!=1:
                    gaps.append({'binding_id':old['binding_id'],'properties':[p['property_id']],
                        'reason':'previous_binding_source_changed_or_not_unique','otype_scope':old['otype_scope']})
                    break
                selected=next(iter(choices.values()));nd=selected['definition'];np=selected['output_profile']
                mapped.append({**p,'definition_version':nd['definition_version'],'definition_hash':nd['content_sha256'],
                    'output_profile_ref':{'id':np['profile_id'],'version':np['version'],'content_sha256':np['content_sha256']}})
            else:
                mapped.append(p)
        if len(mapped)!=len(old['property_bindings']):continue
        b, review = review_binding({**old, 'registry_release_ref': registry_ref,'property_bindings':mapped,
            'previous_binding_ref':{'id':old['binding_id'],'content_sha256':old['content_sha256']}})
        bindings.append(b); reviews.append(review)
    root = app.registry.root / 'releases' / registry_ref['id'] / 'origin'
    manifest_files = {f['path']: f['file_sha256'] for f in registry['candidate']['manifest']['content_files']}
    for item in plans:
        relative = item['path']
        path = local_file(root, relative)
        pin = sha256(path.read_bytes()).hexdigest()
        if manifest_files.get(relative) != pin:
            raise ValueError('Knowledge plan is not pinned by the accepted registry: ' + relative)
        bs, rs, gs = bind_claim_plan(registry, content, loads(path.read_bytes()), otype=item['otype'],
            registry_ref=registry_ref, plan_ref={'path': relative, 'file_sha256': pin})
        bindings.extend(bs); reviews.extend(rs); gaps.extend({'otype': item['otype'], **g} for g in gs)
    bindings = list({b['binding_id']: b for b in bindings}.values())
    reviews = list({r['review_id']: r for r in reviews}.values())
    release_id = 'reviewed-knowledge-' + digest({'registry': registry_ref, 'bindings': bindings})[:20]
    destination = Path(destination) / release_id
    if not destination.exists():
        package_content(base_path / 'origin', destination, release_id=release_id, registry_ref=registry_ref,
                        bindings=bindings, reviews=reviews)
    app.knowledge.validate(destination)
    return {'destination': str(destination), 'release_id': release_id, 'bindings': len(bindings),
            'otype_counts': {t: sum(t in b['otype_scope'] for b in bindings) for t in sorted({t for b in bindings for t in b['otype_scope']})},
            'gaps': gaps, 'content_rewritten': False, 'scientific_source_labels_upgraded': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime-root', type=Path)
    p.add_argument('--plans', required=True, type=Path)
    p.add_argument('--output-root', required=True, type=Path)
    p.add_argument('--import-release', action='store_true')
    p.add_argument('--registry-release')
    p.add_argument('--base-runtime-root',type=Path)
    p.add_argument('--no-activate',action='store_true')
    args = p.parse_args()
    root = data_root(args.runtime_root)
    app = Application(root)
    result = build(app, loads(args.plans.read_bytes()), args.output_root, registry_release=args.registry_release,
        base_app=Application(data_root(args.base_runtime_root)) if args.base_runtime_root else None)
    if args.import_release:
        with InstanceLock(root):
            result['import_result'] = app.knowledge.import_release(Path(result['destination']),activate=not args.no_activate)
    print(canonical(result).decode())


if __name__ == '__main__':
    main()
