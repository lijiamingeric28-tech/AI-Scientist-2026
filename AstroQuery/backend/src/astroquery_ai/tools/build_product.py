"""Build existing frontend assets and a clean wheel or Windows snapshot."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

from astroquery_ai.runtime.paths import build_root, frontend_dist, source_product


def remove_generated(path: Path, parent: Path):
    target, owner = path.resolve(), parent.resolve()
    if target == owner or not target.is_relative_to(owner) or path.is_symlink():
        raise SystemExit('Refusing to remove a path outside its generated-output owner')
    if target.exists():
        shutil.rmtree(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows', action='store_true', help='Build the existing Windows executables instead of a wheel')
    args = parser.parse_args()
    product, output = source_product(), build_root()
    frontend = product / 'frontend'
    target = frontend_dist()
    owner = product if target.resolve().is_relative_to(product.resolve()) else output
    if target.resolve() == product.resolve() or target.resolve() == output.resolve():
        raise SystemExit('Frontend output must be a dedicated subdirectory')
    if not target.resolve().is_relative_to(owner.resolve()):
        raise SystemExit('Frontend output must stay inside product or configured build output')
    vite = frontend / 'node_modules/vite/bin/vite.js'
    node = shutil.which('node')
    if not node or not vite.is_file():
        raise SystemExit('Install the existing frontend lockfile dependencies in product/frontend first (npm ci)')
    subprocess.run([node, str(vite), 'build', '--outDir', str(target), '--emptyOutDir'], cwd=frontend, check=True)
    if args.windows:
        from .build_windows import main as build_windows
        sys.argv = [sys.argv[0]]
        build_windows()
    else:
        remove_generated(product / 'build', product)
        subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation',
                        '--wheel-dir', str(output / 'wheels'), str(product)], check=True)


if __name__ == '__main__':
    main()
