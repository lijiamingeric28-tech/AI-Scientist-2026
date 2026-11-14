"""Package and validate Dot's exact author format; optional normal import."""
import argparse
from pathlib import Path
from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.paths import data_root
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.science.author_release import build_release


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',type=Path)
    p.add_argument('--author-package',type=Path,required=True)
    p.add_argument('--registry-release',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--import-release',action='store_true')
    p.add_argument('--activate',action='store_true')
    a=p.parse_args();app=Application(data_root(a.data_root))
    registry=app.registry.load(a.registry_release)
    ref={'id':registry['manifest']['release_id'],'version':1,'content_sha256':registry['manifest']['content_sha256']}
    manifest=build_release(a.author_package,a.output,ref)
    release=app.knowledge.validate(a.output)
    result={'release_id':manifest['release_id'],'content_sha256':manifest['content_sha256'],
        'counts':manifest['counts'],'validated':True,'activated':False,'scientific_review_claimed':False}
    if a.activate and not a.import_release:p.error('--activate requires --import-release')
    if a.import_release:
        from astroquery_ai.runtime.lifecycle import InstanceLock
        with InstanceLock(app.root):
            with app.repository.read() as c:
                if c.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone():
                    p.error('wait for active jobs before changing the default knowledge release')
            result.update(app.knowledge.import_release(a.output,activate=a.activate))
    print(canonical(result).decode())


if __name__=='__main__':main()
