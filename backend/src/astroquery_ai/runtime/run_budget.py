"""Additional immutable run ceiling; historical campaign accounting stays intact."""
from .codec import canonical, loads, utcnow
from .errors import DomainError


def activate(repo, run_id, cap_micros, calibration_cap_micros):
    if not run_id or any(type(v) is not int or v < 0 for v in (cap_micros, calibration_cap_micros)):
        raise ValueError('A run needs an identifier and nonnegative integer ceilings')
    key = 'execution_run:' + run_id
    with repo.transaction() as conn:
        row = conn.execute('SELECT payload FROM settings WHERE key=?', (key,)).fetchone()
        if row:
            saved = loads(row[0])
            if (saved['cap_micros'], saved['calibration_cap_micros']) != (cap_micros, calibration_cap_micros):
                raise DomainError('BUDGET_IMMUTABLE', '不能通过恢复修改本轮费用上限')
            return saved
        saved = {'run_id': run_id, 'cap_micros': cap_micros,
                 'calibration_cap_micros': calibration_cap_micros, 'created_at': utcnow()}
        conn.execute('INSERT INTO settings(key,revision,payload) VALUES(?,1,?)', (key, canonical(saved)))
        return saved


def bind(repo, conn, task_id, run_id):
    if not conn.execute('SELECT 1 FROM settings WHERE key=?', ('execution_run:' + run_id,)).fetchone():
        raise DomainError('RUN_BUDGET_MISSING', '本轮费用围栏尚未登记')
    key = 'execution_run_task:' + task_id
    row = conn.execute('SELECT payload FROM settings WHERE key=?', (key,)).fetchone()
    if row:
        if loads(row[0])['run_id'] != run_id:
            raise DomainError('RUN_BUDGET_CHANGED', '不能更换任务所属费用围栏')
        return
    conn.execute('INSERT INTO settings(key,revision,payload) VALUES(?,1,?)',
                 (key, canonical({'run_id': run_id, 'task_id': task_id})))


def usage(conn, run_id, *, calibration=False):
    row = conn.execute("""SELECT
        coalesce(sum(CASE WHEN a.status IN ('settled','not_dispatched')
            THEN coalesce(a.actual_micros,a.reserved_micros) ELSE a.reserved_micros END),0),
        coalesce(sum(CASE WHEN a.status IN ('reserved','dispatched') THEN a.reserved_micros ELSE 0 END),0)
        FROM attempts a JOIN tasks t ON t.task_id=a.task_id
        JOIN settings s ON s.key='execution_run_task:'||a.task_id
        WHERE json_extract(cast(s.payload as text),'$.run_id')=?"""
        + (" AND t.kind='validation'" if calibration else ''), (run_id,)).fetchone()
    return {'committed_micros': row[0], 'inflight_micros': row[1]}


def check(repo, conn, task, reservation, *, defer_for_settlement=False):
    member = conn.execute('SELECT payload FROM settings WHERE key=?', ('execution_run_task:' + task['task_id'],)).fetchone()
    if not member:
        return
    run_id = loads(member[0])['run_id']
    row = conn.execute('SELECT payload FROM settings WHERE key=?', ('execution_run:' + run_id,)).fetchone()
    if not row:
        raise DomainError('RUN_BUDGET_MISSING', '本轮费用围栏缺失，禁止调用')
    scope = loads(row[0])
    for calibration, limit in [(False, scope['cap_micros']), *(
            [(True, scope['calibration_cap_micros'])] if task['kind'] == 'validation' else [])]:
        spent = usage(conn, run_id, calibration=calibration)
        if spent['committed_micros'] + reservation > limit:
            if (defer_for_settlement and spent['inflight_micros']
                    and spent['committed_micros'] - spent['inflight_micros'] + reservation <= limit):
                from .throughput import DispatchDeferred
                raise DispatchDeferred('run-budget-settlement:' + run_id, .5)
            raise DomainError('CAMPAIGN_BUDGET_EXHAUSTED', '本轮新增模型费用已达到授权上限',
                run_id=run_id, cap_micros=limit, committed_micros=spent['committed_micros'],
                calibration=calibration)
