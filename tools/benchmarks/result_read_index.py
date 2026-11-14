"""Repeatable 5000-record/30-sample isolated result-page benchmark.

Run from AstroQuery using the development Python environment:
    .venv/Scripts/python.exe tools/benchmarks/result_read_index.py

All SQLite/artifact/cache writes live in TemporaryDirectory. No Application,
scientific provider, main runtime database, or server startup is involved.
The baseline preserves DeliveryService's existing decoded-snapshot cache and
projects the current row contract in full before serializing its first page.
This is a service/serialization comparison, not browser/network latency or a
claim about the original product's pre-change baseline.
"""
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend' / 'src'))

from astroquery_ai.application.result_views import record_list  # noqa: E402
from astroquery_ai.runtime.codec import canonical  # noqa: E402
from tests.rebuild.test_result_read_index import page, setup_delivery  # noqa: E402


def summarize(values):
    return {'p50_ms': round(statistics.median(values), 2),
            'p95_ms': round(sorted(values)[28], 2), 'samples': len(values)}


def main():
    with tempfile.TemporaryDirectory(prefix='result-page-benchmark-') as temporary:
        repo, service, tid, _ = setup_delivery(Path(temporary), count=5000)
        start = time.perf_counter()
        first = page(repo, service, tid, limit=50)
        cold = (time.perf_counter() - start) * 1000
        warm, baseline = [], []
        for _ in range(30):
            start = time.perf_counter()
            response = page(repo, service, tid, limit=50)
            canonical(response)
            warm.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            with repo.read() as conn:
                decoded = service.read_for_display(conn, tid, 'delivery')
                projected = record_list(decoded)
                canonical({'items': projected[:50], 'total': len(projected)})
            baseline.append((time.perf_counter() - start) * 1000)
        print(json.dumps({'synthetic_rows': 5000, 'cold_build_ms': round(cold, 2),
            'page_json_bytes': len(canonical(first)), 'warm_index': summarize(warm),
            'decoded_snapshot_full_projection_baseline': summarize(baseline)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
