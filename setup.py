"""Package the application and its reviewed resources. Vite owns the single frontend build."""
from pathlib import Path
import sys

from setuptools import find_packages, setup

root = Path(__file__).parent
resources = root / 'resources'
frontend = root / 'frontend/dist'


def data_files(directory):
    return sorted(p.relative_to(directory).as_posix() for p in directory.rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts and p.name != '__init__.py')


packages = find_packages('backend/src') + ['astroquery_ai_resources']
directories = {'': 'backend/src', 'astroquery_ai_resources': 'resources'}
data = {'astroquery_ai': ['schemas/*.json', 'schemas/**/*.json'], 'astroquery_ai_resources': data_files(resources)}
if (frontend / 'index.html').is_file():
    packages.append('astroquery_ai_resources.frontend')
    directories['astroquery_ai_resources.frontend'] = 'frontend/dist'
    data['astroquery_ai_resources.frontend'] = data_files(frontend)
elif 'bdist_wheel' in sys.argv:
    raise SystemExit('Build the interface in frontend with npm ci and npm run build before packaging the wheel.')

setup(packages=packages, package_dir=directories, package_data=data, include_package_data=False)
