"""Freeze only the runtime dependency closure from the verified build environment."""
from importlib import metadata
from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from astroquery_ai.runtime.paths import source_product


def main():
    ROOT = source_product()
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    pending = [(Requirement(item), '') for item in project['project']['dependencies']]
    seen, selected = set(), {}
    while pending:
        requirement, context_extra = pending.pop()
        if requirement.marker and not requirement.marker.evaluate({'extra': context_extra}):
            continue
        name = canonicalize_name(requirement.name)
        distribution = metadata.distribution(name)
        if distribution.version not in requirement.specifier:
            raise SystemExit('Installed version violates runtime specification: ' + name)
        selected[name] = distribution.version
        for extra in {'', *requirement.extras}:
            if (name, extra) in seen:
                continue
            seen.add((name, extra))
            pending.extend((Requirement(item), extra) for item in distribution.requires or [])
    output = ROOT / 'requirements-windows.lock'
    output.write_text('# Verified Windows x64 / Python 3.12 runtime closure. No build/test packages.\n' +
        ''.join(name + '==' + version + '\n' for name, version in sorted(selected.items())), encoding='utf-8')
    print('Locked', len(selected), 'runtime packages')


if __name__ == '__main__':
    main()
