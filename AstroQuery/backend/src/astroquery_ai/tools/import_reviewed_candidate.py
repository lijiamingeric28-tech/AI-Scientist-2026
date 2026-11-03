"""Install an explicitly pinned, reviewed candidate through the normal registry."""
import argparse
from pathlib import Path
from astroquery_ai.runtime.paths import data_root

from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.codec import canonical, loads
from astroquery_ai.runtime.lifecycle import InstanceLock
from astroquery_ai.runtime.errors import DomainError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--science-config", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument('--amendment', type=Path)
    parser.add_argument('--amendment-sha256')
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument('--no-activate',action='store_true',help='Install the immutable version without changing task defaults.')
    args = parser.parse_args()
    args.runtime_root = data_root(args.runtime_root)
    amendment = None
    if args.amendment:
        from hashlib import sha256
        raw = args.amendment.read_bytes()
        if not args.amendment_sha256 or sha256(raw).hexdigest() != args.amendment_sha256:
            parser.error('amendment requires the exact file SHA256')
        amendment = loads(raw)
    elif args.amendment_sha256:
        parser.error('--amendment-sha256 requires --amendment')
    with InstanceLock(args.runtime_root):
        app = Application(args.runtime_root)
        try:
            result = app.registry.import_candidate(args.package, args.science_config,
                manifest_sha256=args.manifest_sha256, config_sha256=args.config_sha256, amendment=amendment,activate=not args.no_activate)
        except DomainError as exc:
            print(canonical({'error':exc.code,'message':str(exc),'details':exc.details}).decode())
            raise SystemExit(1)
        loaded = app.registry.load(result["release_id"])
        result.update(definitions=len(loaded.get('definition_views',loaded['definitions'])), profiles=len(loaded.get('profile_views',loaded['profiles'])),
                      scientific_records=len(loaded['science'].get('by_ref',loaded['science']['records'])), paid_calls_started=0,
                      software_capability_qualification="separate_not_granted_by_import")
        destination = args.runtime_root / "validation" / (result["release_id"] + "-import.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(canonical(result))
        print(canonical(result).decode())


if __name__ == "__main__":
    main()
