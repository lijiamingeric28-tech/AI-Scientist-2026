"""Package runtime astronomy modules without importing Astropy's test suites."""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

def runtime_module(name):
    return 'tests' not in name.split('.') and 'conftest' not in name.split('.')

hiddenimports = ['astropy.tests.runner', 'numpy.lib.recfunctions']
for package in ('astropy.constants', 'astropy.units', 'astropy.coordinates', 'astropy.time',
                'astropy.table', 'astropy.utils.iers', 'astropy.io.fits', 'astropy.io.ascii', 'astropy.io.votable'):
    hiddenimports += collect_submodules(package, filter=runtime_module, on_error='warn once')
datas = collect_data_files('astropy', excludes=['**/tests/**'])
datas += [(source, destination) for source, destination in collect_data_files('astropy', include_py_files=True)
          if source.endswith(('_parsetab.py', '_lextab.py'))]
excludedimports = ['astropy.visualization', 'astropy.samp']
