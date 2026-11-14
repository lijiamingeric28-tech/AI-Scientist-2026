"""Small exact local-label maps; scientific identities remain server-owned."""
from astroquery_ai.runtime.codec import digest
from astroquery_ai.runtime.errors import DomainError

VERSION = 'model-bindings/1'


def labels(values, prefix):
    """Stable within one input. Repaired subsets retain the original map."""
    values = list(values)
    if len(set(values)) != len(values) or any(not isinstance(v, str) or not v for v in values):
        raise DomainError('MODEL_BINDING_INPUT', '模型局部引用的原始身份不唯一')
    return {f'{prefix}{i + 1}': value for i, value in enumerate(values)}


def invert(mapping):
    return {value: key for key, value in mapping.items()}


def resolve(mapping, label):
    if not isinstance(label, str) or label not in mapping:
        raise DomainError('MODEL_BINDING_REFERENCE', '模型引用不在本次输入中')
    return mapping[label]


def binding_ref(groups, *, context):
    body = {'schema_version':VERSION, 'groups':groups, 'context':context}
    return {**body, 'binding_hash':digest(body)}


def property_labels(spec):
    return labels([b['property_id'] for b in spec['properties']], 'P')


def property_views(spec, factory, mapping=None):
    mapping = mapping or property_labels(spec)
    inverse = invert(mapping)
    return [{**factory(b), 'property_id':inverse[b['property_id']]} for b in spec['properties']]


def map_fields(value, mappings, *, expand=False, strict=True):
    """Only declared reference fields, never replace words in scientific text."""
    def mapped(item,mapping):
        if isinstance(item,list):return [mapped(v,mapping) for v in item]
        if isinstance(item,dict):
            result=map_fields(item,mappings,expand=expand,strict=strict)
            # A reference field's JSON Schema must expose the same labels as
            # its supplied values. Do not rewrite descriptions or other text.
            if isinstance(item.get('enum'),list):result['enum']=[mapped(v,mapping) for v in item['enum']]
            if 'const' in item:result['const']=mapped(item['const'],mapping)
            if item.get('type')=='array' and isinstance(item.get('items'),dict):
                result['items']=mapped(item['items'],mapping)
            return result
        if item is None:return None
        if expand:return resolve(mapping,item) if strict else mapping.get(item,item)
        return invert(mapping).get(item,item)
    if isinstance(value,list):return [map_fields(v,mappings,expand=expand,strict=strict) for v in value]
    if isinstance(value,dict):
        return {k:mapped(v,mappings[k]) if k in mappings else map_fields(v,mappings,expand=expand,strict=strict)
                for k,v in value.items()}
    return value


def component_bindings(record, *, operation):
    return binding_ref({'U':labels([c['component_id'] for c in record['uncertainty']['components']], 'U')},
        context={'operation':operation,'measurement_id':record['measurement_id'],
                 'source_hash':record.get('content_sha256')})


def compact_evidence(spans):
    """Same immutable spans, repeated text stored once; aliases are never merged."""
    seen, result = {}, []
    for span in spans:
        item = dict(span)
        text = item.get('text')
        if text in seen:
            item.pop('text',None)
            item['text_ref'] = seen[text]
        elif text is not None:seen[text] = item['span_id']
        result.append(item)
    return result
