"""Resolve literal registered labels without interpreting new user conditions."""
from copy import deepcopy
import re


def ground_registered_labels(parsed, text, bindings):
    if not text or parsed['property_operation'] not in {'add', 'remove', 'replace'}:
        return parsed, []
    result = deepcopy(parsed)
    expanded, repairs = [], []
    for prop in result['properties']:
        hits = []
        for binding in bindings:
            definition = binding['definition']
            for name in [definition['name_cn'], definition['name_en'], *definition['aliases']]:
                if not name or len(name) <= len(prop['text']):
                    continue
                for match in re.finditer(r'(?<![A-Za-z0-9_])' + re.escape(name) + r'(?![A-Za-z0-9_])', text, re.I):
                    if match.start() <= prop['start'] and prop['end'] <= match.end():
                        hits.append((len(name), binding['property_id'], match.start(), match.end()))
        if not hits:
            continue
        longest = [h for h in hits if h[0] == max(h[0] for h in hits)]
        choices = {(pid, start, end) for _, pid, start, end in longest}
        if len(choices) != 1:
            continue  # Literal ambiguity is still a question, not a preference.
        pid, start, end = choices.pop()
        replacement = {'text': text[start:end], 'start': start, 'end': end}
        repairs.append({'basis': 'literal_registered_property_name_containing_grounded_request',
            'property_id': pid, 'before': dict(prop), 'after': replacement})
        prop.update(replacement)
        expanded.append((start, end))
    for key in ['conditions', 'unknown_fragments']:
        result[key] = [fragment for fragment in result[key] if not any(
            start <= fragment['start'] and fragment['end'] <= end for start, end in expanded)]
    result['properties'] = list({(p['start'], p['end'], p['text']): p for p in result['properties']}.values())
    return result, repairs
