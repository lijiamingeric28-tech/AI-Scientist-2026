"""JSON and PDF share exactly one frozen execution report model."""
from collections import Counter
from datetime import datetime, timezone
import json
import re

from .execution_view import project, job_brief, instant

REPORT_STATES = {'completed':'已完成','running':'运行中','succeeded':'成功','failed':'失败',
    'partial':'部分影响','recovered':'已恢复','unresolved':'未解决','resolved':'已处理',
    'cancelled':'已取消','pending':'待处理','waiting_resource':'等待资源','ready':'等待运行',
    'ended_unknown':'结束状态未记录','not_run':'未运行'}


def report(application, task_id, at_seq=None):
    data = project(application, task_id, at_seq)
    keys = ('schema_version', 'task_id', 'source_task_id', 'title', 'cursor', 'as_of', 'lifecycle',
            'created_at', 'terminal_at', 'terminal_seq', 'wall_seconds', 'human_wait_seconds',
            'summary', 'stages', 'waits', 'pauses', 'delivery_ref', 'history_complete')
    return {**{key: data[key] for key in keys},
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'definitions': {'wall_seconds': '任务起点至终态，包含人工等待；导出不延长任务',
            'stage_seconds': '同阶段访问区间并集', 'job_seconds': '作业实际运行区段并集',
            'exception_events': '已保存的失败与安排重试事件数',
            'issues': '按业务作业关联的执行问题数，科研判断单列',
            'http_attempts': '任务级网络访问次数，不推定作业归属'},
        'jobs': [job_brief(j) for j in data['jobs'].values()],
        'issues': data['issues'], 'key_events': [e for e in data['events']
            if e['category'] in {'stage', 'review', 'delivery', 'insight'} or e['exception']],
        'service_states': dict(Counter(r['status'] for r in data['services'])),
        'limitations': ([] if data['history_complete'] else ['历史过程记录不完整']) +
            ['HTTP访问按任务展示，缺少明确作业引用时不关联到具体作业']}


def duration(value):
    if value is None:
        return '未记录'
    n = round(value)
    return f'{n // 60}分{n % 60}秒'


def pdf_bytes(body):
    import fitz
    doc = fitz.open()
    page, y = None, 0

    def line(text, size=10):
        nonlocal page, y
        # Mixed fonts keep Latin IDs and dates proportional alongside Chinese.
        # Built-in fonts also work on an installed desktop without web fonts.
        lines, current, width = [], '', 0
        for char in text:
            font = 'helv' if ord(char) < 256 else 'china-s'
            length = fitz.get_text_length(char, fontname=font, fontsize=size)
            if width + length > 490:
                lines.append(current)
                current, width = '', 0
            current += char
            width += length
        lines.append(current)
        for text_line in lines:
            if page is None or y > 780:
                page = doc.new_page(width=595, height=842)
                page.insert_text((48, 818), f'AstroQuery / {len(doc)}', fontsize=9)
                y = 52
            x = 48
            for run in re.findall(r'[\x00-\xff]+|[^\x00-\xff]+', text_line):
                font = 'helv' if ord(run[0]) < 256 else 'china-s'
                page.insert_text((x, y), run, fontname=font, fontsize=size, color=(.11,.18,.14))
                x += fitz.get_text_length(run, fontname=font, fontsize=size)
            y += size * 1.7

    line('AstroQuery 运行报告', 19)
    line(body['title'], 12)
    line(f"任务 {body['task_id']}")
    line(f"统计游标 {body['cursor']} / {REPORT_STATES.get(body['lifecycle'],body['lifecycle'])}")
    line(f"生成时间 {body['generated_at']}")
    line(f"墙钟 {duration(body['wall_seconds'])}，其中人工等待 {duration(body['human_wait_seconds'])}", 12)
    line('下列原始时点为 UTC；网页按浏览器本地时间显示。')
    line('执行时间线（横轴为任务起点后的分钟数）', 14)
    if body['wall_seconds'] and body['wall_seconds'] > 0:
        start = instant(body['created_at'])
        axis_y = y
        left, width = 135, 410
        for i, stage in enumerate(body['stages']):
            top = axis_y + i * 24
            page.insert_text((48, top + 11), stage['name'], fontname='china-s', fontsize=10)
            page.draw_line((left, top + 14), (left + width, top + 14), color=(.82, .86, .83))
            for visit in stage['visits']:
                if not visit['end']:
                    continue
                x = left + (instant(visit['start']) - start) / body['wall_seconds'] * width
                length = max(1, visit['seconds'] / body['wall_seconds'] * width)
                page.draw_rect((x, top, x + length, top + 13), color=(.3, .45, .35), fill=(.72, .82, .74),
                               dashes='[2 2]' if visit['local_repair'] else None)
        y = axis_y + len(body['stages']) * 24 + 18
        line(f"起点 0 分钟 / 终点 {body['wall_seconds'] / 60:.2f} 分钟；虚线表示复检回访")
    line('阶段访问与耗时', 14)
    for stage in body['stages']:
        line(f"{stage['name']}：{duration(stage['seconds'])}，{len(stage['visits'])}次访问")
        for v in stage['visits']:
            line(f"  #{v['seq']} {v['start']} → {v['end'] or '结束时点未记录'}")
    line('作业与异常统计', 14)
    summary = body['summary']
    line(f"业务作业 {summary['jobs']} / 运行区段 {summary['run_segments']} / 峰值并行 {summary['peak_running_jobs']}")
    line(f"安排重试 {summary['retries']} / 资源等待 {summary['resource_waits']} / 异常事件 {summary['exception_events']}")
    for name, count in summary['job_states'].items():
        line(f'{REPORT_STATES.get(name,name)}：{count}')
    line('异常、恢复与科研判断', 14)
    for issue in body['issues']:
        prefix = f"#{issue['seq']}" if issue['seq'] is not None else '服务访问'
        line(f"{prefix} {issue['message']} / {REPORT_STATES.get(issue['recovery'],issue['recovery'])}")
        if issue.get('impact'):
            line(issue['impact'])
        for action in issue['actions']:
            line(f"  #{action['seq']} {action['at']} {action['label']} {REPORT_STATES.get(action.get('status'),action.get('status') or '')}")
        for attempt in issue.get('service_attempts', []):
            state = '取得响应' if attempt['status']=='completed' else REPORT_STATES.get(attempt['status'],attempt['status'])
            response = attempt['status_code'] if attempt['status_code'] is not None else '响应未记录'
            line(f"  {attempt['start']} {attempt['service']} / {state} / HTTP {response}")
    line('关键事件', 14)
    for event in body['key_events']:
        line(f"#{event['seq']} {event['at']} {event['label']} {event.get('object_label') or ''}")
    line('统计口径与历史缺口', 14)
    for label in body['definitions'].values():
        line(label)
    for label in body['limitations']:
        line(label)
    payload = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return payload


def json_bytes(body):
    return json.dumps(body, ensure_ascii=False, indent=2).encode('utf-8')
