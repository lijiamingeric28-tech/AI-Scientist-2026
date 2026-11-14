import {parseExecutionExamples} from './registryExecution.js'

const split = value => Array.isArray(value) ? value : String(value || '').split(/[\n,，]/).map(v=>v.trim()).filter(Boolean)
const clone = value => JSON.parse(JSON.stringify(value || {}))
const conditions = value => String(value||'').split('\n').map(x=>x.trim()).filter(Boolean).map(x=>x.startsWith('{')||x.startsWith('[')?JSON.parse(x):x)
export const REGISTRY_KINDS = {types:'天体类型',properties:'性质定义',bindings:'类型绑定'}
export function registryEditorCloseAction(values,baseline,busy=false) {
  if(busy)return 'blocked'
  const keys=[...new Set([...Object.keys(values),...Object.keys(baseline)])]
  const normalize=(object,key)=>['create_profile','custom_output','native_coordinate_only'].includes(key)?Boolean(object[key]):String(object[key]??'')
  return keys.some(key=>normalize(values,key)!==normalize(baseline,key))?'confirm':'close'
}
export function registryQuery(filters={}, mode='cards') {
  const out = {}
  for (const key of ['keyword','type_id','family_id','origin','status','sort','workspace_id','release_id']) {
    const value = String(filters[key] || '').trim()
    if (value && (value !== 'all'||key==='keyword')) out[key] = value
  }
  if (mode !== 'scope') { out.offset=Math.max(0,Number(filters.offset)||0);out.limit=mode==='table' ? ([25,50,100].includes(Number(filters.limit)) ? Number(filters.limit) : 50) : 24 }
  return out
}
export function registryGraphQuery(filters,scene={},budget=80) { return {...registryQuery(filters,'scope'),view:scene.view||'overview',...(scene.focus_id ? {focus_id:scene.focus_id} : {}),limit:[80,120,200].includes(budget)?budget:80} }
export function readRegistryEditorCatalog(api,cache,view={},signal) {
  const scope={...registryQuery({workspace_id:view.workspace_id,release_id:view.release_id},'scope'),projection:'full'}
  return cache.read(`summary:${JSON.stringify(scope)}`,()=>api.summary(scope,{signal}),signal)
}
export function registryWritable(summary,stale,busy) { return !stale && !busy && summary?.view==='draft' && summary?.workspace?.status==='draft' }
export function canPublishRegistry(summary,validation,stale,busy) { return registryWritable(summary,stale,busy) && validation?.state==='passed' && validation.workspace_revision===summary.workspace.revision && Boolean(validation.id) }
export function createRegistryOperationTokens(create=()=>crypto.randomUUID()) {const tokens=new Map();return {get:key=>{if(!tokens.has(key))tokens.set(key,create());return tokens.get(key)},ack:key=>tokens.delete(key)}}
export function createRegistryReadCache(limit=32) {
  const entries=new Map(),pending=new Map();let generation=0
  return {
    peek:key=>entries.get(key)?.value,
    fresh:key=>entries.get(key)?.generation===generation,
    clear:()=>{generation++;entries.clear();pending.clear()},
    invalidate:()=>{generation++;pending.clear()},
    read(key,loader,signal){
      const hit=entries.get(key)
      if(hit?.generation===generation){entries.delete(key);entries.set(key,hit);return Promise.resolve(hit.value)}
      const existing=pending.get(key)
      if(existing&&!existing.signal?.aborted)return existing.promise
      const epoch=generation,entry={signal}
      entry.promise=Promise.resolve(loader()).then(value=>{if(!signal?.aborted&&epoch===generation){entries.delete(key);entries.set(key,{value,generation});while(entries.size>limit)entries.delete(entries.keys().next().value)}return value}).finally(()=>{if(pending.get(key)===entry)pending.delete(key)})
      pending.set(key,entry);return entry.promise
    },
  }
}
export function registryLaunch(hash) { const route=new URLSearchParams(String(hash||'').replace(/^#/,''));return route.get('settings')==='registry' ? {tab:'registry',studioMode:'registry'} : route.get('settings')==='knowledge'||route.get('view')==='knowledge' ? {tab:'knowledge',studioMode:'graph'} : {tab:null,studioMode:null} }
export function adaptRegistryGraph(data={}) {
  return {...data,nodes:(data.nodes||[]).map(n=>({...n,source_kind:n.source_kind||n.kind,kind:n.kind==='aggregate'?'aggregate':(n.source_kind||n.kind)==='type'?'property':'entry',...((n.source_kind||n.kind)==='type'?{property_id:undefined,properties:undefined,count:n.property_count??n.count}:{}),record_id:n.record_id||n.item_id||n.entity_id||n.id.replace(/^(type|property):/,''),category:n.category||n.family_id||n.kind})),edges:data.edges||[],categories:data.categories||[]}
}
export function registryProfileRef(profile={}) { return profile.ref||profile.profile_ref||{id:profile.profile_id||profile.id,version:profile.version,content_sha256:profile.content_sha256} }
export function registryProfileKey(profile={}) {const ref=registryProfileRef(profile);return JSON.stringify({id:ref.id,version:String(ref.version),content_sha256:ref.content_sha256})}
export function registryBindingProfile(property,selected,current) {const profile=(property?.output_profiles||[]).find(p=>registryProfileKey(p)===selected);if(profile)return registryProfileRef(profile);if(current&&registryProfileKey(current)===selected)return current;if(!selected&&property?.output_profiles?.[0])return registryProfileRef(property.output_profiles[0]);throw new Error('精确输出方案已变化，请重新选择并核对版本与内容指纹')}
export function registryOutputProfile(v,baseline={}) {
  const profile=clone(baseline)
  profile.unit={...profile.unit,canonical_symbol:v.unit||null,dimension:v.dimension||null,kind:v.unit_kind,...(v.unit_kind==='physical'?{parser_format:v.parser_format,parser_version:v.parser_version}:{}),...(v.unit_kind==='dimensionless'?{semantic_kind:v.unit_semantic_kind}:{})}
  if(v.unit_kind==='not_applicable')profile.unit={kind:'not_applicable'}
  profile.representation={...profile.representation,kind:v.representation_kind,scale:v.representation_scale||'1',offset:v.representation_offset||'0',...(v.reference_value?{reference_value:v.reference_value}:{}),...(v.reference_unit?{reference_unit:v.reference_unit}:{}),...(v.native_coordinate_only?{native_coordinate_only:true}:{})}
  if(!v.native_coordinate_only)delete profile.representation.native_coordinate_only
  if(v.system_id)profile.representation.system_ref={id:v.system_id,version:v.system_version,content_sha256:v.system_hash}
  profile.object_scale_id=v.scale_id||profile.object_scale_id
  if(v.conversion_policy_ref)profile.conversion_policy_ref=v.conversion_policy_ref
  return profile
}
export function normalizeRegistryCapabilities(value={}) {
  const policies=new Map()
  for(const policy of value.conversion_policies||[]){
    const ref=policy.ref||policy.reference||{id:policy.policy_id||policy.id,version:policy.version,content_sha256:policy.content_sha256}
    const id=registryProfileKey(ref),description=policy.description||policy.name_cn||policy.label||''
    policies.set(id,{...policy,id,canonical_id:ref.id,ref,label:`${ref.id} · v${ref.version??'未提供'} · ${ref.content_sha256||'未提供内容指纹'}${description&&description!==ref.id?` · ${description}`:''}`})
  }
  return {...value,conversion_policies:[...policies.values()]}
}
export function registryDefaultUserPolicy(item,capabilities,current='') {
  if(item?.id||current||!capabilities?.user_execution_protocol)return current
  return capabilities.conversion_policies?.find(policy=>policy.user_declared===true)?.id||''
}
export function registryCondition(kind,value,negate=false) {if(!['otype','subject_class'].includes(kind)||!value)throw new Error('请选择已有类型或科学主体');const condition={[kind]:value};return negate?{not:condition}:condition}
export function registryEditorValues(kind,item={}) {
  const d=item.definition||{},p=item.output_profile||item.output_profiles?.[0]||{},unit=p.unit||d.unit||{},representation=p.representation||{}
  return {label:item.label||d.name_cn||'',description:item.description||d.description||d.definition_text||'',aliases:(item.aliases||d.aliases||[]).join('\n'),code:item.code||'',parent_id:item.parent_id||'',color:item.color||'',status:item.status||'active',conditions:(item.conditions||[]).map(x=>typeof x==='string'?x:JSON.stringify(x)).join('\n'),excluded_conditions:(item.excluded_conditions||[]).map(x=>typeof x==='string'?x:JSON.stringify(x)).join('\n'),source_note:item.source_note||item.notes||'',property_id:item.property_id||'',family_id:item.family_id||d.family_id||'',quantity_key:d.quantity_key||'',quantity_kind:d.quantity_kind||'',subject_class_id:d.subject_class_id||'',scope:d.scope||'whole_object',value_kind:d.value_schema?.kind||d.value_kind||'real',categories:Object.entries(d.value_schema?.categories||{}).map(([k,v])=>`${k}=${v}`).join('\n'),predicate_id:d.value_schema?.predicate_id||'',subject_role:d.value_schema?.subject_role||'',object_role:d.value_schema?.object_role||'',scale_id:p.object_scale_id||'',unit:unit.canonical_symbol||'',dimension:unit.dimension||'',unit_kind:unit.kind||'physical',unit_semantic_kind:unit.semantic_kind||'',parser_format:unit.parser_format||'generic',parser_version:unit.parser_version||'source_declared',representation_kind:representation.kind||p.representation_kind||'linear',representation_scale:representation.scale||'1',representation_offset:representation.offset||'0',reference_value:representation.reference_value||'',reference_unit:representation.reference_unit||'',native_coordinate_only:representation.native_coordinate_only||false,system_id:representation.system_ref?.id||'',system_version:representation.system_ref?.version||'',system_hash:representation.system_ref?.content_sha256||'',coordinate_meaning:p.coordinate_meaning||p.output_coordinate_meaning||'',conversion_policy:p.conversion_policy_ref?registryProfileKey(p.conversion_policy_ref):'',type_id:item.type_id||'',property_key:item.property_key||'',custom_output:!!item.output_profile,profile_id:item.profile_ref?registryProfileKey(item.profile_ref):'',display_order:item.display_order??0,profile_index:0,execution_examples:JSON.stringify(item.execution_examples||[])}
}
export function registryEditorPayload(kind,v,item={}) {
  if (kind==='types') return {label:v.label,description:v.description,aliases:split(v.aliases),...(item.id && item.origin!=='user' ? {} : {code:v.code,parent_id:v.parent_id}),...(v.color?{color:v.color}:{}),status:v.status,conditions:conditions(v.conditions),source_note:v.source_note}
  if (kind==='bindings') return {type_id:v.type_id,property_key:v.property_key,...(item.profile_ref?{profile_ref:item.profile_ref}:{}),...(item.output_profile&&!v.custom_output?{output_profile:null}:{}),conditions:conditions(v.conditions),excluded_conditions:conditions(v.excluded_conditions),display_order:Number(v.display_order)||0,status:v.status,source_note:v.source_note}
  const definition=clone(item.definition),profiles=clone(item.output_profiles||[]),index=Number(v.profile_index)||0
  const profile=registryOutputProfile(v,profiles[index]||{})
  Object.assign(definition,{description:v.description,family_id:v.family_id})
  if (!item.id) Object.assign(definition,{name_cn:v.label,aliases:split(v.aliases),quantity_key:v.quantity_key,quantity_kind:v.quantity_kind,subject_class_id:v.subject_class_id,scope:v.scope,value_schema:{kind:v.value_kind}})
  if(!item.id&&v.value_kind==='category')definition.value_schema.categories=Object.fromEntries(String(v.categories||'').split('\n').filter(x=>x.trim()).map(line=>{const index=line.indexOf('=');if(index<1)throw new Error('类别值需按“代码=含义”填写');return[line.slice(0,index).trim(),line.slice(index+1).trim()]}))
  if(!item.id&&v.value_kind==='relation')Object.assign(definition.value_schema,{predicate_id:v.predicate_id,subject_role:v.subject_role,object_role:v.object_role})
  if(profiles.length||!item.id||v.create_profile)profiles[index]=profile
  const examples=parseExecutionExamples(v.execution_examples)
  return {label:v.label,description:v.description,aliases:split(v.aliases),family_id:v.family_id,definition,output_profiles:profiles,status:v.status,source_note:v.source_note+(v.coordinate_meaning?`\n输出值含义：${v.coordinate_meaning}`:''),...(examples.length||Object.hasOwn(item,'execution_examples')?{execution_examples:examples}:{})}
}
