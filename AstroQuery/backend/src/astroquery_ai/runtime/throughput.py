"""Small per-model pacing controller; waiting is not failed scientific work."""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
import time


class DispatchDeferred(Exception):
    def __init__(self, resource, seconds):
        self.resource = resource
        self.seconds = max(0.05, seconds)
        super().__init__('resource not ready')


class ModelTraffic:
    # Public Beijing floor, 70% initially. Unknown workspace/other-app limits
    # are assumptions, not a claim that this account owns the public quota.
    def __init__(self, tpm=3_500_000, rpm=600, clock=time.monotonic):
        self.tpm, self.rpm, self.clock = tpm, rpm, clock
        self.entries = defaultdict(deque)
        self.next_send = defaultdict(float)
        self.backoffs = defaultdict(int)

    def reserve(self, model, tokens):
        now = self.clock()
        entries = self.entries[model]
        while entries and entries[0]['at'] <= now - 60:
            entries.popleft()
        wait = self.next_send[model] - now
        if entries and (len(entries) >= self.rpm or sum(e['tokens'] for e in entries) + tokens > self.tpm):
            wait = max(wait, entries[0]['at'] + 60 - now)
        if wait > 0:
            raise DispatchDeferred('model-rate:' + model, wait)
        ticket = {'at': now, 'tokens': tokens,'previous_next_send':self.next_send[model]}
        entries.append(ticket)
        self.next_send[model] = now + max(60 / self.rpm, 60 * tokens / self.tpm)
        ticket['next_send']=self.next_send[model]
        return ticket

    def cancel(self,model,ticket):
        """Release an unsent local reservation; never refund a dispatched call."""
        self.entries[model]=deque(x for x in self.entries[model] if x is not ticket)
        if self.next_send[model]==ticket.get('next_send'):
            self.next_send[model]=ticket['previous_next_send']

    async def acquire(self, model, tokens, *, defer):
        while True:
            try:
                return self.reserve(model, tokens)
            except DispatchDeferred as wait:
                if defer:
                    raise
                await asyncio.sleep(min(wait.seconds, 30))

    def settle(self, model, ticket, usage, *, limited=False, retry_after=None):
        if usage and usage.get('prompt_tokens') is not None and usage.get('completion_tokens') is not None:
            ticket['tokens'] = usage['prompt_tokens'] + usage['completion_tokens']
        if limited:
            self.backoffs[model] += 1
            delay = retry_after if retry_after is not None else min(60, 2 ** min(self.backoffs[model], 6))
            self.next_send[model] = max(self.next_send[model], self.clock() + max(0.1, delay))
        else:
            self.backoffs[model] = max(0, self.backoffs[model] - 1)


def rate_token_estimate(messages, byte_safety_bound, output_bound):
    """Calibratable estimate, distinct from the strict byte/image safety bound."""
    text_bytes = 0
    for message in messages:
        content = message.get('content', '')
        texts = [content] if isinstance(content, str) else [p['text'] for p in content if p.get('type') == 'text']
        text_bytes += sum(len(t.encode('utf-8')) for t in texts)
    visual_and_protocol = max(0, byte_safety_bound - text_bytes)
    return int(text_bytes / 2.5 + visual_and_protocol + output_bound) + 1


def shared_window_delay(conn, model, incoming, *, tpm=3_500_000, rpm=600):
    """The existing SQLite call ledger shares the minute window across gateways.

    All keys/workspaces configured for this local account share the model bucket.
    No owner/task/key can reset it. The single-instance executor remains in use.
    """
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    rows = conn.execute("""SELECT a.dispatched_at,
        CASE WHEN a.input_tokens IS NOT NULL AND a.output_tokens IS NOT NULL
            THEN a.input_tokens+a.output_tokens
            ELSE coalesce(json_extract(CAST(d.payload AS TEXT),'$.rate_token_estimate'),
                          cast(a.input_bound/2.5 AS INTEGER)+a.output_bound) END AS tokens
        FROM attempts a LEFT JOIN objects d ON d.task_id=a.task_id AND d.kind='model_dispatch'
            AND d.object_id=a.attempt_id AND d.version=1
        WHERE a.model=? AND a.status IN ('dispatched','unknown','settled')
            AND a.dispatched_at>? ORDER BY a.dispatched_at""",
        (model, (now - timedelta(seconds=60)).isoformat())).fetchall()
    used, count = sum(r['tokens'] for r in rows), len(rows)
    for row in rows:
        if count < rpm and used + incoming <= tpm:
            return 0.0
        used -= row['tokens']
        count -= 1
        delay = (datetime.fromisoformat(row['dispatched_at']) + timedelta(seconds=60) - now).total_seconds()
        if count < rpm and used + incoming <= tpm:
            return max(0.05, delay)
    return 0.0
