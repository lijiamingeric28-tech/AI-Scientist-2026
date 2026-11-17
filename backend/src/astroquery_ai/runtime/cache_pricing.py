"""Beijing usage-based cache estimates, separate from an actual provider invoice.

Sources: https://help.aliyun.com/zh/model-studio/context-cache
https://help.aliyun.com/zh/model-studio/qwen3-8-flash
https://help.aliyun.com/zh/model-studio/qwen3-8-max
"""
VERSION = 'bailian-beijing-cache-2026-11-16'


def rates(model, input_tokens):
    # Hundredths of micro-yuan/token; retain fractional creation prices exactly.
    if model == 'qwen3.8-flash':
        return dict(ordinary=80, output=270, implicit=10, explicit=10, creation=125)
    if model == 'qwen3.8-max':
        return dict(ordinary=1200, output=3600, implicit=150, explicit=100, creation=1500)
    if model == 'qwen3.7-plus':
        unit = 200 if input_tokens <= 256000 else 600
        return dict(ordinary=unit, output=unit*4, implicit=unit//5, explicit=unit//10, creation=unit*5//4)
    return None


def explicit_request(request):
    return any(isinstance(m.get('content'), list) and any(
        isinstance(p, dict) and isinstance(p.get('cache_control'), dict) and
        p['cache_control'].get('type') == 'ephemeral' for p in m['content'])
        for m in request.get('messages', []))


def reservation_cost(model, inputs, outputs, request):
    from .budget import price_for
    price = price_for(model, inputs)
    r = rates(model, inputs)
    if not explicit_request(request) or r is None:
        return price.cost(inputs, outputs)
    return (inputs * max(r['ordinary'], r['creation']) + outputs*r['output'] + 99)//100


def usage_estimate(model, inputs, outputs, receipt):
    from .budget import price_for
    original = price_for(model, inputs).cost(inputs, outputs)
    cache = receipt.get('prompt_cache') or {}
    identity = receipt.get('provider_identity') or cache.get('provider_identity')
    usage = receipt.get('usage')
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get('prompt_tokens_details')
    details = details if isinstance(details, dict) else {}
    completion = usage.get('completion_tokens_details')
    completion = completion if isinstance(completion, dict) else {}
    r = rates(model, inputs)
    result = {'version': VERSION, 'list_price_micros': original, 'estimated_micros': original,
              'basis': 'list_price_no_cache_evidence', 'provider_bill_verified': False,
              'input_tokens': inputs, 'output_tokens': outputs,
              'reasoning_tokens': completion.get('reasoning_tokens')}
    if not isinstance(identity, dict) or identity.get('region') != 'cn-beijing' or r is None:
        return result
    explicit = cache.get('mode') == 'explicit'
    hit = details.get('cached_tokens')
    created = details.get('cache_creation_input_tokens', 0)
    known = (type(hit) is int and type(created) is int and min(hit, created) >= 0 and hit+created <= inputs
             and (not explicit or 'cache_creation_input_tokens' in details))
    if not known:
        # Missing details are not a zero-priced cache hit. Explicit creation may have cost extra.
        cost = (inputs*max(r['ordinary'],r['creation'])+outputs*r['output']+99)//100 if explicit else original
        result.update(estimated_micros=cost, basis='upper_bound_missing_cache_usage' if explicit else 'list_price_missing_cache_usage', cache_usage_known=False)
        return result
    ordinary = inputs-hit-created
    cost = (ordinary*r['ordinary']+hit*r['explicit' if explicit else 'implicit']+
            created*r['creation']+outputs*r['output']+99)//100
    result.update(estimated_micros=cost, basis='provider_usage_with_cache_not_invoice', cache_usage_known=True,
                  ordinary_input_tokens=ordinary,cached_input_tokens=hit,cache_creation_input_tokens=created,
                  net_cache_savings_micros=original-cost,mode='explicit' if explicit else 'implicit')
    return result
