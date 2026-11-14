"""Explicit maintainer enqueue of independent supplements for one pinned sample.

Normal read-only sample HTTP routes stay unchanged. The ordinary backend worker
performs all model calls, qualification, budgets and durable report publication.
"""
import argparse
import json
import time
from pathlib import Path

from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.codec import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', required=True, type=Path)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--delivery-id', required=True)
    parser.add_argument('--requests', required=True, type=Path)
    parser.add_argument('--confirm-sample-update', required=True, action='store_true')
    parser.add_argument('--progress', required=True, type=Path)
    parser.add_argument('--concurrency', type=int, default=2, choices=range(1, 9))
    args = parser.parse_args()
    requests = json.loads(args.requests.read_text(encoding='utf-8'))
    if not isinstance(requests, list) or not 1 <= len(requests) <= 128:
        parser.error('Provide a finite list of at most 128 exact supplementary requests')
    app = Application(args.runtime_root)
    app.registry.load()  # Full installed scientific verification, never a trust marker.
    results, pending, cursor = [], {}, 0
    while cursor < len(requests) or pending:
        while cursor < len(requests) and len(pending) < args.concurrency:
            result = app.material_analysis.submit(args.task_id, args.delivery_id, requests[cursor], sample_update=True)
            results.append(result)
            if result['status'] in {'queued', 'running'}:
                pending[result['run_id']] = len(results) - 1
            cursor += 1
            print('submitted', cursor, '/', len(requests), result['status'], flush=True)
        for run_id, index in list(pending.items()):
            result = app.material_analysis.status(args.task_id, run_id)
            if result['status'] != results[index]['status']:
                print(result['status'], result.get('stage'), result.get('reason'), flush=True)
            results[index] = result
            if result['status'] not in {'queued', 'running'}:
                pending.pop(run_id)
        args.progress.parent.mkdir(parents=True, exist_ok=True)
        args.progress.write_bytes(canonical(results))
        if pending:
            time.sleep(2)
    print('finished', {state: sum(r['status'] == state for r in results) for state in {r['status'] for r in results}}, flush=True)


if __name__ == '__main__':
    main()
