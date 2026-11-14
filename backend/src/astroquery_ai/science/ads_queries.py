"""Small ADS expression checker. Scientific expressions remain model choices.

Whole-query validation checks positive target/quantity coverage. The separately
compiled quantity side also supports ADS set subtraction.
"""
import re
import unicodedata
from astroquery_ai.runtime.codec import digest
from astroquery_ai.runtime.errors import DomainError

FIELDS={'abs','title','abstract','keyword','body','full'}
TOKEN=re.compile(r'\s*("(?:\\.|[^"\\])*"|[():]|[^\s():"]+)')


def invalid(message, **details):
    raise DomainError('LITERATURE_EXPRESSION_INVALID',message,422,**details)


def syntax_help():
    return {'fields':sorted(FIELDS), 'operators':['AND','OR'],
        'rules':'Every term must have a field, or be inside a field:(...) group. Quote multiword text and literal punctuation, including parentheses. No functions, wildcards, ranges or caller doctype filters.',
        'examples':['(title:"Object A" OR abs:"Object A") AND (abs:"quantity (native)" OR body:quantity)',
                    'abs:("Object A" OR "Object B") AND body:("quantity name" OR method)']}


def parse(expression, *, allow_exclusions=False):
    if not isinstance(expression,str) or not expression.strip() or len(expression)>8192 or any(c in expression for c in '\n\r\0'):
        invalid('查询表达缺失、过长或包含控制字符')
    tokens=[];spans=[];position=0
    while position<len(expression):
        if not expression[position:].strip():break
        match=TOKEN.match(expression,position)
        if not match:invalid('查询引号或字符无法解析')
        token=match.group(1)
        if allow_exclusions and token.upper() in {'AND','OR','NOT'}:
            token=token.upper()
        tokens.append(token);spans.append((match.start(1),match.end(1)));position=match.end()
    if len(tokens)>512:invalid('查询表达结构过大')
    index=0
    def fail(message):
        at=min(max(index-1,0),len(tokens)-1)
        offset=spans[at][0] if spans else 0
        invalid(message,error_offset=offset,error_token=tokens[at] if tokens else None,
                error_excerpt=expression[max(0,offset-60):offset+100])
    def primary(default=None,depth=0):
        nonlocal index
        if depth>24 or index>=len(tokens):fail('括号、字段或运算符缺少操作数')
        token=tokens[index];index+=1
        if token=='(':
            node=group_expression(default,depth+1)
            if index>=len(tokens) or tokens[index]!=')':fail('括号不配对')
            index+=1;return node
        if token in {')',':','AND','OR','NOT'}:fail('运算符位置无效')
        if index<len(tokens) and tokens[index]==':':
            index+=1;field=token.removeprefix('=')
            if field not in FIELDS:fail('字段未在当前API通道内核验')
            return primary((field,token.startswith('=')),depth+1)
        if default is None:fail('所有检索词必须有明确字段')
        if not token.startswith('"') and (token.startswith(('~','+','-')) or any(c in token for c in '{}[];^~') or re.fullmatch(r'NEAR\d+',token,re.I)):
            fail('不支持该直接查询运算')
        if re.search(r'(?<!\\)[*?]',token):fail('不支持活动通配符；原名中的符号须按字面量转义')
        if token.startswith('"'):
            if not token.endswith('"'):fail('引号不配对')
        elif '"' in token or token in {'AND','OR','NOT'}:fail('字面量无效')
        return ('term',default[0],default[1],token)
    def difference(default,depth):
        nonlocal index
        left=primary(default,depth)
        while allow_exclusions and index<len(tokens):
            if tokens[index]=='NOT':
                index+=1
            elif tokens[index:index+2]==['AND','NOT']:
                index+=2
            else:
                break
            left=('not',(left,primary(default,depth)))
        return left
    def and_expression(default=None,depth=0):
        nonlocal index
        values=[difference(default,depth)]
        while index<len(tokens) and tokens[index] not in {')','OR'}:
            if tokens[index]=='AND':index+=1
            elif allow_exclusions:break
            values.append(difference(default,depth))
        return values[0] if len(values)==1 else ('and',tuple(values))
    def or_expression(default=None,depth=0):
        nonlocal index
        values=[and_expression(default,depth)]
        while index<len(tokens) and tokens[index]=='OR':
            index+=1;values.append(and_expression(default,depth))
        return values[0] if len(values)==1 else ('or',tuple(values))
    def group_expression(default=None,depth=0):
        # ADS assigns implicit whitespace AND lower precedence than explicit OR.
        values=[or_expression(default,depth)]
        while allow_exclusions and index<len(tokens) and tokens[index]!=')':
            values.append(or_expression(default,depth))
        return values[0] if len(values)==1 else ('and',tuple(values))
    tree=group_expression()
    if index!=len(tokens):invalid('存在未闭合的表达式')
    return tree


def terms(tree, *, positive_only=False):
    if tree[0]=='term':
        return {tree}
    children=tree[1][:1] if positive_only and tree[0]=='not' else tree[1]
    return set().union(*(terms(child,positive_only=positive_only) for child in children))


def literal_value(term):
    value=term[3]
    if value.startswith('"'):value=value[1:-1]
    return re.sub(r'\\(.)',r'\1',value)


def normalized_name(value):
    return ' '.join(unicodedata.normalize('NFKC',value).split()).casefold()


def serialize(tree):
    if tree[0]=='term':return ('=' if tree[2] else '')+tree[1]+':'+tree[3]
    operator={'and':' AND ','or':' OR ','not':' NOT '}[tree[0]]
    return '('+operator.join(serialize(c) for c in tree[1])+')'


def branch_masks(tree,target,quantity):
    if tree[0]=='term':return {(1 if tree in target else 0)|(2 if tree in quantity else 0)}
    children=[branch_masks(c,target,quantity) for c in tree[1]]
    if tree[0]=='or':return set().union(*children)
    result={0}
    for child in children:result={a|b for a in result for b in child}
    return result


def checked_expression(row,names):
    channel=row.get('channel')
    if channel not in {'metadata','body'}:invalid('只允许通道1(metadata)和3(body)')
    target,quantity,query=(parse(row.get(key)) for key in ('target_query','quantity_query','query'))
    t,q,all_terms=terms(target),terms(quantity),terms(query)
    if t&q or not t or not q or all_terms!=t|q:invalid('目标和性质子句必须准确覆盖实际查询')
    known={normalized_name(n) for n in names}
    if {normalized_name(literal_value(x)) for x in t}!=known:
        invalid('目标子句不是所选已核名称；不得虚构别名或对象关系')
    if branch_masks(query,t,q)!={3}:invalid('每条OR分支必须同时含目标和性质约束')
    if channel=='metadata' and any(x[1]=='body' for x in all_terms):invalid('通道1不能查询正文')
    if channel=='body' and not any(x[1]=='body' for x in all_terms):invalid('通道3必须实际包含正文范围')
    if any(normalized_name(literal_value(x)) in known for x in q):invalid('性质子句不能退化为目标名称')
    return serialize(query)+' AND doctype:(article OR eprint)'


def query_memberships(plan):
    """One physical query can sponsor multiple property families without repeats."""
    return plan.get('family_links') or [{'family_id':plan['family_id'],'selected_property_ids':plan['selected_property_ids']}]


def merge_plans(plans):
    grouped={}
    for plan in plans:
        key=plan['query']
        if key not in grouped:grouped[key]={**plan,'family_links':[],'model_expressions':[]}
        current=grouped[key]
        links={x['family_id']:x for x in current['family_links']}
        for link in query_memberships(plan):
            if link['family_id'] not in links:current['family_links'].append(link)
        for expression in plan.get('model_expressions',[]):
            if expression not in current['model_expressions']:current['model_expressions'].append(expression)
        current['selected_property_ids']=sorted({p for x in current['family_links'] for p in x['selected_property_ids']})
    result=[]
    for value in grouped.values():
        value['query_id']='query-'+digest({k:v for k,v in value.items() if k!='query_id'})
        result.append(value)
    return result
