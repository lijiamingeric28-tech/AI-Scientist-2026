"""Reproducible astronomy dependencies; all external I/O belongs to ScientificHTTP."""


def configure_offline_tables():
    from astropy.utils import iers
    # Includes the leap-second auto-update path. An explicit, recorded import
    # may install newer tables; library background HTTP is never authorized.
    iers.conf.auto_download = False
