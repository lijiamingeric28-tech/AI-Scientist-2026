"""Generate the approved demo follow-up once through the real application API."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

TASK = '827c01d6-0a9a-4e3e-bba8-db6a3aa3f5b5'
REQUEST_ID = 'sn2014j-demo-ebv-followup-20261114-v1'
QUESTION = (
    '接着刚才的结果，只看 SN 2014J 的视线 E(B−V)。选出三篇不同论文的原报测量，'
    '保留误差和条件，用表格和误差图比较，并结合本任务知识库解释它们是否能直接比较。'
    '再用 A_V=R_V E(B−V) 做一个可调 R_V 的示意试算，注明输入来自哪条测量，'
    '原文和知识依据都要能点开。试算固定使用其中一条已引用的 E(B−V)，'
    'R_V 范围 1–5、步长 0.1、初始值 3.1；明确这是演示参数，不是 SN 2014J 的科学采用值。'
)

def get(base, path):
    with urlopen(base + path, timeout=180) as response:
        return json.load(response)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', default='http://127.0.0.1:8781/api')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    path = f'/tasks/{TASK}'
    head = get(args.api, path + '/delivery')
    before = get(args.api, path + '/agent/messages')['messages']
    existing = [m for m in before if m.get('request_id') == REQUEST_ID]
    if existing:
        print('Reusing saved request:', existing[-1]['id'], existing[-1]['status'], flush=True)
    else:
        body = {'content': QUESTION, 'request_id': REQUEST_ID,
                'delivery_id': head['delivery_id'], 'delivery_revision': head['revision'],
                'snapshot_ref': head['snapshot_ref']}
        request = Request(args.api + path + '/agent/chat', data=json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json'}, method='POST')
        with urlopen(request, timeout=900) as stream, (args.output / 'generation.sse').open('wb') as log:
            for line in stream:
                log.write(line)
                log.flush()
                if line.startswith(b'event:'):
                    print(line.decode().strip(), flush=True)
    messages = get(args.api, path + '/agent/messages')['messages']
    (args.output / 'messages.json').write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding='utf-8')
    answer = next((m for m in messages if m.get('request_id') == REQUEST_ID), None)
    if not answer or answer['status'] != 'complete':
        raise SystemExit('Follow-up is not complete; saved state retained, no automatic paid retry.')
    blocks = answer.get('answer', {}).get('blocks', [])
    print(json.dumps({'answer_id': answer['id'], 'status': answer['status'],
        'blocks': [b['type'] for b in blocks], 'citations': len(answer['citations']),
        'model': answer.get('model'), 'fallback': answer.get('fallback')}, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    main()
