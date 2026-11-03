"""Frozen desktop/browser/isolated-worker entry. Never bundles credentials."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def worker():
    from astroquery_ai.runtime.parser_worker import main

    try:
        main()
    except BaseException as exc:
        sys.stdout.buffer.write(
            json.dumps(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "code": getattr(exc, "code", "PARSER_FAILED"),
                }
            ).encode()
        )
        raise SystemExit(1)


async def self_check(root):
    from astroquery_ai.runtime.repository import Repository
    from astroquery_ai.runtime.parsing import Parsers
    import pymupdf
    import httpx
    import webview
    import langgraph
    import astropy
    from astroquery_ai.runtime.application import Application
    from astroquery_ai.science.astrometry import propagate

    check = root / "validation" / "startup-check"
    check.mkdir(parents=True, exist_ok=True)
    repo = Repository(check / "check.sqlite3")
    application = Application(check / "application")
    # Initialize the same verified TLS transport used to download source papers.
    async with httpx.AsyncClient():
        pass
    with application.repository.read() as conn:
        startup_attempts = conn.execute("SELECT count(*) FROM attempts").fetchone()[0]
    position = propagate(
        {
            "frame": "icrs",
            "coordinate_role": "source_native",
            "pm_ra_convention": "already_multiplied_by_cos_dec",
            "ra_deg": "0",
            "dec_deg": "0",
            "parallax_mas": "100",
            "pm_ra_cosdec_masyr": "0",
            "pm_dec_masyr": "0",
            "radial_velocity_kms": "0",
            "reference_epoch": {"value": "2016", "format": "jyear", "scale": "tcb"},
        },
        {"value": "2016", "format": "jyear", "scale": "tcb"},
    )
    path = check / "synthetic-parser.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=300, height=200)
        page.insert_text((20, 30), "SYNTHETIC startup check; value 0")
        doc.save(path)
    result = await Parsers().run("inspect_pdf", path, timeout=30)
    image = await Parsers().run("page_image", path, page=1, timeout=30)
    from astropy.io import fits

    table_path = check / "synthetic-table.fits"
    fits.BinTableHDU.from_columns(
        [
            fits.Column(name="Name", format="20A", array=["SYNTHETIC_AQ"]),
            fits.Column(name="Value", format="D", unit="m", array=[0.0]),
            fits.Column(name="e_Value", format="D", unit="m", array=[0.2]),
        ]
    ).writeto(table_path, overwrite=True)
    parsed_table = await Parsers().run(
        "structured_table",
        table_path,
        format="fits",
        table_id="SYNTHETIC/measurements",
        id_column="Name",
        aliases=["SYNTHETIC_AQ"],
        timeout=30,
    )
    table_rows = parsed_table["resources"][0]["tables"][0]["rows"]
    fits_ok = (
        len(table_rows) == 1
        and float(table_rows[0]["Value"]) == 0
        and float(table_rows[0]["e_Value"]) == 0.2
    )
    with repo.read() as conn:
        database_version = conn.execute("PRAGMA user_version").fetchone()[0]
    report = {
        "schema_version": "startup-check/1",
        "synthetic": True,
        "paid_calls": 0,
        "database_version": database_version,
        "loaded_modules": [httpx.__name__, webview.__name__, langgraph.__name__],
        "page_count": result["page_count"],
        "image_png": image.startswith(b"\x89PNG"),
        "application_initialized": True,
        "https_transport_initialized": True,
        "model_attempts_at_startup": startup_attempts,
        "astropy_version": astropy.__version__,
        "astrometric_math_imported": float(position["ra_deg"]) == float(position["dec_deg"]) == 0,
        "fits_isolated_parser": fits_ok,
        "passed": result["page_count"] == 1
        and image.startswith(b"\x89PNG")
        and startup_attempts == 0
        and fits_ok
        and float(position["ra_deg"]) == float(position["dec_deg"]) == 0,
    }
    (check / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report))


def main():
    if "--parser-worker" in sys.argv:
        worker()
        return
    parser = argparse.ArgumentParser(description="AstroQuery AI")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--import-registry", type=Path)
    parser.add_argument("--import-knowledge", type=Path)
    parser.add_argument("--import-credentials", type=Path)
    parser.add_argument("--import-history", type=Path)
    args = parser.parse_args()
    if args.port is not None and not 1024 <= args.port <= 65535:
        parser.error("port must be within 1024..65535")
    from astroquery_ai.runtime.paths import data_root

    root = data_root(args.data_root)
    os.environ["ASTROQUERY_DATA_ROOT"] = str(root)
    if any(
        (args.import_registry, args.import_knowledge, args.import_credentials, args.import_history)
    ):
        from astroquery_ai.runtime.application import Application
        from astroquery_ai.runtime.lifecycle import InstanceLock

        with InstanceLock(root):
            app = Application(root)
            if args.import_registry:
                result = app.registry.import_release(args.import_registry)
            elif args.import_knowledge:
                result = app.knowledge.import_release(args.import_knowledge)
            elif args.import_credentials:
                public = app.configuration.import_csv(args.import_credentials)
                result = {
                    "saved_revision": public["saved_revision"],
                    "restart_required": public["restart_required"],
                }
            else:
                result = app.legacy.import_database(args.import_history)
            print(json.dumps(result, ensure_ascii=False))
    elif args.self_check:
        asyncio.run(self_check(root))
    elif args.browser:
        import uvicorn
        from astroquery_ai.api.http import create_app

        uvicorn.run(create_app(root), host="127.0.0.1", port=args.port or 8000, log_level="warning", use_colors=False)
    else:
        from astroquery_ai.api.desktop import run_embedded

        run_embedded(port=args.port)


if __name__ == "__main__":
    main()
