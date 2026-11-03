"""Assemble exact reviewed batch files with an installed baseline consumer."""
import argparse
from pathlib import Path
from astroquery_ai.registry.assembly import assemble
from astroquery_ai.runtime.codec import canonical
from astroquery_ai.runtime.errors import DomainError


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-consumer', required=True, type=Path)
    p.add_argument('--batch-root', required=True, type=Path)
    p.add_argument('--selection-file', required=True, type=Path)
    p.add_argument('--selection-sha256', required=True)
    p.add_argument('--destination', required=True, type=Path)
    p.add_argument('--reference-amendment',type=Path)
    p.add_argument('--reference-amendment-sha256')
    args = p.parse_args()
    try:
        print(canonical(assemble(**vars(args))).decode())
    except DomainError as exc:
        print(canonical({'error':exc.code,'message':str(exc),'details':exc.details}).decode())
        raise SystemExit(1)


if __name__ == '__main__':
    main()
