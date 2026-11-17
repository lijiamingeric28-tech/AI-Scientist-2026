"""Lossless, task-local prompt prefix planning; never a scientific answer cache."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import json
import os
import time

from .codec import digest, loads, new_id
from .provider import provider_identity

VERSION = 'single-query-prefix/5'
OPERATIONS = {'paper_admission', 'paper_batch', 'result_comparison'}
MODELS = {'qwen3.8-flash', 'qwen3.7-plus', 'qwen3.8-max'}
FIRST = ('schema', 'output_schema', 'output_shape', 'instruction')
FIXED = {'native_unit_check', 'subject_and_role_cautions', 'independent_decisions',
         'decision_order', 'verification_priority', 'encoding_note', 'response_contract'}
CONTEXT = ('target', 'properties', 'confirmed_quantity_wording')


def _fixed(key):
    return (key in FIRST or key in FIXED or key.endswith(
        ('_rule', '_rules', '_instruction', '_contract')))


def ordered_prompt(text, *, include_query_scope=False):
    """Reorder only root object members. Nested values and array order stay intact."""
    try:
        value = loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or not any(k in value for k in FIRST):
        return None
    fixed = [k for k in FIRST if k in value]
    fixed += sorted(k for k in value if _fixed(k) and k not in fixed)
    if not fixed:
        return None
    # This query's identity and complete property definitions repeat in every
    # batch. Cache them too, keyed by their literal values and task, rather than
    # stopping at the schema and paying for the same query scope each time.
    if include_query_scope:
        fixed += [k for k in CONTEXT if k in value and k not in fixed]
    rest = [k for k in CONTEXT if k in value and k not in fixed]
    rest += sorted(k for k in value if k not in fixed and k not in rest)
    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

    def field(key):
        return encode(key) + ':' + encode(value[key])
    prefix = '{' + ','.join(field(k) for k in fixed)
    suffix = (',' if rest else '') + ','.join(field(k) for k in rest) + '}'
    assert loads(prefix + suffix) == value
    return prefix, suffix


class PromptCache:
    """Observe reuse within this task only; never wait or prewarm to create a hit."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.entries = OrderedDict()

    def prepare(self, messages, *, task_id, profile, values, future_calls=0, allow_explicit=True):
        mode = os.environ.get('ASTROQUERY_PROMPT_CACHE_MODE', 'auto')
        if mode not in {'off', 'implicit', 'auto', 'explicit'}:
            mode = 'off'
        meta = {'version': VERSION, 'policy': mode, 'mode': 'implicit',
                'reordered': False, 'logical_input_hash': digest(messages),
                'provider_identity': provider_identity(values.get('dashscope_base_url', ''))}
        if mode == 'off' or profile.operation not in OPERATIONS or profile.model not in MODELS:
            return messages, meta
        # Only the first input object is reorganized; following feedback remains in place.
        result = deepcopy(messages)
        for message_index, message in enumerate(result):
            content = message.get('content')
            part = content[0] if isinstance(content, list) and content else None
            text = content if isinstance(content, str) else part.get('text') if isinstance(part, dict) and part.get('type') == 'text' else None
            if text is None:
                continue
            ordered = ordered_prompt(text, include_query_scope=profile.operation == 'paper_admission')
            if ordered is None:
                continue
            prefix, suffix = ordered
            identity = digest({'task': task_id, 'model': profile.model, 'operation': profile.operation,
                'profile': profile.version, 'connection': {k: values.get(k) for k in ('dashscope_base_url', 'dashscope_api_key')},
                'preceding_messages': result[:message_index], 'prefix': prefix})
            now = self.clock()
            entry = self.entries.get(identity)
            if entry is None or now - entry['at'] > 300:
                entry = {'at': now, 'completed': 0, 'input': 0, 'cached': 0,
                         'pending': False, 'ready_until': 0, 'unsupported': False,
                         'implicit_completed': 0, 'implicit_input': 0, 'implicit_cached': 0,
                         'prefix_tokens': 0}
                self.entries[identity] = entry
            self.entries.move_to_end(identity)
            while len(self.entries) > 256:
                self.entries.popitem(last=False)
            # 8KiB avoids annotating tiny prefixes. The provider is authoritative about tokens.
            eligible = bool(meta['provider_identity'] and len(prefix.encode()) >= 8192 and suffix != '}')
            observed_low_hits = (entry['implicit_completed'] >= 2 and
                                 entry['implicit_cached'] < entry['implicit_input'] * .5)
            better = True
            if entry['prefix_tokens'] and entry['implicit_completed']:
                from .cache_pricing import rates
                r = rates(profile.model, entry['implicit_input']//entry['implicit_completed'])
                implicit_saving = ((r['ordinary']-r['implicit']) * entry['implicit_cached'] /
                                   entry['implicit_completed'])
                explicit_saving = (r['ordinary']-r['explicit']) * entry['prefix_tokens']
                # Creation is already sunk while the prefix is live. On renewal,
                # amortize its premium over only the known queued work, not an
                # imagined future conversation. Implicit may cache a longer prefix.
                if entry['ready_until'] <= now:
                    explicit_saving -= (max(0,r['creation']-r['ordinary']) *
                                        entry['prefix_tokens'] / (future_calls+1))
                better = explicit_saving > implicit_saving
            explicit = (eligible and allow_explicit and not entry['unsupported'] and not entry['pending'] and
                (mode == 'explicit' or mode == 'auto' and better and
                 (entry['ready_until'] > now or observed_low_hits and future_calls >= 2)))
            creation_token = None
            if explicit:
                # Multimodal providers can cache a whole message regardless of the
                # annotated part. Use a dedicated SAME-ROLE message, containing only
                # the fixed root members, so dynamic evidence is never a cache write.
                # Both JSON objects are complete; their disjoint members reconstruct
                # the original object without adding or removing an instruction.
                first = {'type': 'text', 'text': prefix + '}', 'cache_control': {'type': 'ephemeral'}}
                tail = '{' + suffix.removeprefix(',')
                fixed_message = {**message, 'content': [first]}
                variable_message = {**message, 'content': ([{'type': 'text', 'text': tail}, *content[1:]]
                                    if isinstance(content, list) else tail)}
                result[message_index:message_index+1] = [fixed_message, variable_message]
                if entry['ready_until'] <= now:
                    creation_token = new_id()
                    entry['pending'] = creation_token
            elif isinstance(content, str):
                message['content'] = prefix + suffix
            else:
                message['content'][0] = {**part, 'text': prefix + suffix}
            meta.update(mode='explicit' if explicit else 'implicit', reordered=True,
                prefix_sha256=digest(prefix), prefix_bytes=len(prefix.encode()),
                boundary='message' if explicit else 'root_members',
                explicit_expected_cheaper=better if entry['prefix_tokens'] else None,
                observed_prefix_tokens=entry['prefix_tokens'],
                observed_implicit_cached_tokens=(entry['implicit_cached']/entry['implicit_completed']
                    if entry['implicit_completed'] else None),
                expected_additional_calls=future_calls, _identity=identity,
                _creation_token=creation_token,
                wire_input_hash=digest(result))
            return result, meta
        return messages, meta

    def observe(self, meta, usage, *, success, rejected=False):
        entry = self.entries.get(meta.get('_identity'))
        if entry is None:
            return
        if meta.get('_creation_token') and entry['pending'] == meta['_creation_token']:
            entry['pending'] = False
        if rejected:
            entry['unsupported'] = True
        usage = usage if isinstance(usage, dict) else {}
        details = usage.get('prompt_tokens_details')
        details = details if isinstance(details, dict) else {}
        def count(value):
            return value if type(value) is int and value >= 0 else 0
        hit, created = (count(details.get(k)) for k in ('cached_tokens', 'cache_creation_input_tokens'))
        now = self.clock()
        if meta['mode'] == 'explicit' and hit + created > 0:
            entry['ready_until'] = now + 280
            entry['prefix_tokens'] = hit + created
        elif meta['mode'] == 'explicit' and 'cached_tokens' in details and 'cache_creation_input_tokens' in details:
            # A provider can accept the marker without caching a short/unsupported
            # prefix. Do not keep paying creation premiums for that prefix.
            entry['unsupported'] = True
        if not success:
            return
        entry['at'] = now
        entry['completed'] += 1
        entry['input'] += count(usage.get('prompt_tokens'))
        entry['cached'] += hit
        if (meta['mode'] == 'implicit' and type(details.get('cached_tokens')) is int
                and type(usage.get('prompt_tokens')) is int and usage['prompt_tokens'] > 0
                and 0 <= details['cached_tokens'] <= usage['prompt_tokens']):
            entry['implicit_completed'] += 1
            entry['implicit_input'] += usage['prompt_tokens']
            entry['implicit_cached'] += hit


def public_metadata(meta):
    return {k: v for k, v in meta.items() if not k.startswith('_')}
