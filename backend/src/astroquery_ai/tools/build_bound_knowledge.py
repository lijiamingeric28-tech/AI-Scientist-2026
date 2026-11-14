"""Build and validate a bound wrapper; neither invent bindings nor activate it."""
import argparse
from pathlib import Path
from astroquery_ai.runtime.paths import data_root, knowledge_content_root
from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.codec import canonical, loads
from astroquery_ai.science.bound_knowledge import package_content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--content', type=Path, default=knowledge_content_root())
    parser.add_argument('--registry-release', required=True)
    parser.add_argument('--bindings', type=Path, required=True)
    parser.add_argument('--reviews', type=Path, required=True)
    parser.add_argument('--release-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--synthetic', action='store_true', help='Testing only; cannot activate in production.')
    args = parser.parse_args()
    args.data_root = data_root(args.data_root)
    app = Application(args.data_root, allow_synthetic=args.synthetic)
    registry = app.registry.load(args.registry_release)
    manifest = package_content(args.content, args.output, release_id=args.release_id,
        registry_ref={'id': registry['manifest']['release_id'], 'version': 1,
            'content_sha256': registry['manifest']['content_sha256']},
        bindings=loads(args.bindings.read_bytes()), reviews=loads(args.reviews.read_bytes()), synthetic=args.synthetic)
    release = app.knowledge.validate(args.output)
    print(canonical({'release_id': manifest['release_id'], 'content_sha256': manifest['content_sha256'],
        'entries': len(release['entries']), 'bindings': len(release['data']['bindings']),
        'structurally_valid': True, 'activated': False, 'scientific_acceptance': 'not_asserted'}).decode())


if __name__ == '__main__':
    main()
