"""Read-only local API loading benchmark; never creates tasks or exports."""
import argparse
import concurrent.futures
import json
import math
import pathlib
import sqlite3
import statistics
import time
import urllib.request


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8781')
    parser.add_argument('--root', default='runtime-data')
    parser.add_argument('--samples', type=int, default=30)
    parser.add_argument('--optimized', action='store_true')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    conn = sqlite3.connect(pathlib.Path(args.root, 'runtime.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)
    row = conn.execute("select task_id,delivery_ref from tasks where kind not in ('legacy','replay') and delivery_ref is not null order by updated_at desc limit 1").fetchone()
    conn.close()
    scenarios = {
        'registry_directory': ['/api/registry-workbench/summary' + ('?projection=directory' if args.optimized else '')],
        'registry_stats': ['/api/registry-workbench/summary?keyword=mass' + ('&projection=stats' if args.optimized else '')],
        'knowledge_stats': ['/api/knowledge/summary' + ('?projection=stats' if args.optimized else '')],
        'registry_cards': ['/api/registry-workbench/properties?limit=24&offset=0'],
        'registry_graph': ['/api/registry-workbench/graph?limit=80'],
    }
    if row:
        task, raw = row
        delivery = json.loads(raw)
        prefix = f'/api/tasks/{task}'
        scenarios['chat_refresh'] = [prefix + '/state?view=chat'] if args.optimized else [prefix + '/state?view=conversation', prefix + '/presentation?include_chat_activity=true']
        scenarios['record_page'] = [prefix + f'/deliveries/{delivery["id"]}/records?view=list&limit=50&delivery_revision={delivery["version"]}&expected_delivery_revision={delivery["version"]}']

    def read(path):
        with urllib.request.urlopen(args.base_url + path, timeout=90) as response:
            body = response.read()
            if response.status != 200:
                raise RuntimeError(f'Unexpected status {response.status}')
            return len(body)

    result = {'samples': args.samples, 'optimized': args.optimized, 'mode': 'warm scientific preflight; first request reported separately', 'scenarios': {}}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for name, paths in scenarios.items():
            durations, sizes, errors = [], [], []
            for _ in range(args.samples + 1):
                started = time.perf_counter()
                try:
                    size = sum(pool.map(read, paths))
                    sizes.append(size)
                    durations.append((time.perf_counter() - started) * 1000)
                except Exception as exc:
                    errors.append(type(exc).__name__)
            warm = sorted(durations[1:])
            item = {'requests_per_read': len(paths), 'first_ms': round(durations[0], 2) if durations else None,
                    'p50_ms': round(statistics.median(warm), 2) if warm else None,
                    'p95_ms': round(warm[max(0, math.ceil(len(warm) * .95)-1)], 2) if warm else None,
                    'mean_bytes': round(statistics.mean(sizes)) if sizes else None, 'successes': len(durations), 'errors': errors}
            result['scenarios'][name] = item
            print(json.dumps({name: item}), flush=True)
    pathlib.Path(args.output).write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    run()
