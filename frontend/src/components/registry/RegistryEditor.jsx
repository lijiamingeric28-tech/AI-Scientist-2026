import {useEffect,useMemo,useRef,useState} from 'react'
import {useDialogFocus} from '@/hooks/useDialogFocus'
import {registryEditorValues,registryEditorPayload,registryEditorCloseAction,registryProfileRef,registryProfileKey,registryBindingProfile,registryOutputProfile,registryCondition,normalizeRegistryCapabilities,registryDefaultUserPolicy,REGISTRY_KINDS} from '@/lib/registryWorkbench'
import {registryApi} from '@/hooks/useRegistryWorkbench'
import {RegistryExecutionExamples,RegistryExecutionStatus} from './RegistryExecution'
import RegistryFamilySelect from './RegistryFamilySelect'

function optionLabel(option,key) {
  const description=option.label||option.id
  return description===option.id||['profile_id','property_key','conversion_policy'].includes(key)?description:`${option.id} · ${description}`
}

export function RegistryDiscardNotice({busy=false,onContinue,onDiscard,noticeRef}) {
  return <div ref={noticeRef} className="rwb-discard-notice" role="alert" aria-live="polite"><div><strong>有未保存修改</strong><p>关闭后将丢失当前输入。服务器已保存的草稿会保留。</p></div><div><button type="button" disabled={busy} onClick={onContinue}>继续编辑</button><button type="button" disabled={busy} onClick={onDiscard}>放弃未保存修改</button></div></div>
}

function ConditionName({condition,types,subjects}) {
  if(typeof condition!=='object'||!condition)return <span>{String(condition)}</span>
  const [operator,value]=Object.entries(condition)[0]||[]
  if(operator==='otype'||operator==='subject_class'){const options=operator==='otype'?types:subjects;return <span>{operator==='otype'?'天体类型':'科学主体'}为 {options.find(x=>x.id===value)?.label||value}</span>}
  if(operator==='not')return <span>不满足（<ConditionName condition={value} types={types} subjects={subjects}/>）</span>
  return <span>{operator==='all_of'?'同时满足':'满足任一'}（{(Array.isArray(value)?value:[]).map((x,i)=><span key={i}>{i?'；':''}<ConditionName condition={x} types={types} subjects={subjects}/></span>)}）</span>
}
function ConditionEditor({title,value,onChange,types,subjects,busy}) {
  const [kind,setKind]=useState('otype'),[target,setTarget]=useState(''),[negate,setNegate]=useState(false),[combine,setCombine]=useState('separate')
  const rules=String(value||'').split('\n').filter(Boolean).map(line=>{try{return JSON.parse(line)}catch{return line}}),options=kind==='otype'?types:subjects
  const update=items=>onChange(items.map(x=>typeof x==='string'?x:JSON.stringify(x)).join('\n'))
  return <div className="rwb-condition-editor"><strong>{title}</strong><div className="rwb-condition-rules">{rules.map((rule,index)=><div key={index}><ConditionName condition={rule} types={types} subjects={subjects}/><button type="button" disabled={busy} onClick={()=>update(rules.filter((_,i)=>i!==index))}>移除</button></div>)}{!rules.length&&<p>无附加条件</p>}</div><div className="rwb-condition-add"><label>条件依据<select value={kind} disabled={busy} onChange={e=>{setKind(e.target.value);setTarget('')}}><option value="otype">天体类型</option><option value="subject_class">科学主体</option></select></label><label>取值<select value={target} disabled={busy} onChange={e=>setTarget(e.target.value)}><option value="">请选择</option>{options.map(x=><option key={x.id} value={x.id}>{optionLabel(x)}</option>)}</select></label><label>条件关系<select value={combine} disabled={busy} onChange={e=>setCombine(e.target.value)}><option value="separate">添加独立条件</option><option value="all_of">与已有条件同时满足</option><option value="any_of">与已有条件满足任一</option></select></label><label><input type="checkbox" checked={negate} onChange={e=>setNegate(e.target.checked)} disabled={busy}/>不满足此条件</label><button type="button" disabled={!target||busy} onClick={()=>{const rule=registryCondition(kind,target,negate);update(combine==='separate'||!rules.length?[...rules,rule]:[{[combine]:[...rules,rule]}]);setTarget('')}}>添加条件</button></div><small>仅组合已有天体类型与科学主体，不执行自定义脚本。</small></div>
}

export default function RegistryEditor({kind,item:initialItem={},types=[],families=[],capabilities:rawCapabilities={},properties:initialProperties=[],scope={},busy=false,conflict=false,catalogLoading=false,catalogError='',onReloadCatalog,onSave,onClose,onReload}) {
  const [item,setItem]=useState(initialItem),[serverReview,setServerReview]=useState(null),[reviewed,setReviewed]=useState(false),[reloading,setReloading]=useState(false)
  const capabilities=normalizeRegistryCapabilities(rawCapabilities)
  const [values,setValues]=useState(()=>registryEditorValues(kind,item)),[error,setError]=useState('')
  const initialValues=useRef(values),[discardOpen,setDiscardOpen]=useState(false),discardRef=useRef(null),discardOrigin=useRef(null)
  const defaultUserPolicy=kind==='properties'?registryDefaultUserPolicy(item,capabilities):''
  useEffect(()=>{
    if(!defaultUserPolicy)return
    setValues(current=>{
      if(current.conversion_policy)return current
      if(!initialValues.current.conversion_policy)initialValues.current={...initialValues.current,conversion_policy:defaultUserPolicy}
      return {...current,conversion_policy:defaultUserPolicy}
    })
  },[defaultUserPolicy])
  const requestClose=()=>{const action=registryEditorCloseAction(values,initialValues.current,busy||reloading);if(action==='close')onClose();else if(action==='confirm')setDiscardOpen(true)}
  useEffect(()=>{
    if(discardOpen){discardOrigin.current=document.activeElement;discardRef.current?.querySelector('button')?.focus({preventScroll:true})}
    else if(discardOrigin.current?.isConnected){discardOrigin.current.focus({preventScroll:true});discardOrigin.current=null}
  },[discardOpen])
  const [propertySearch,setPropertySearch]=useState(''),[propertyOffset,setPropertyOffset]=useState(0),[propertyPage,setPropertyPage]=useState({items:[],total:0}),[chosenProperty,setChosenProperty]=useState(null),[pickerError,setPickerError]=useState('')
  const scopeKey=JSON.stringify(scope)
  useEffect(()=>{
    if(kind!=='bindings')return
    const controller=new AbortController(),timer=setTimeout(()=>{registryApi.list('properties',{...JSON.parse(scopeKey),keyword:propertySearch,offset:propertyOffset,limit:25},{signal:controller.signal}).then(result=>{if(!controller.signal.aborted){setPropertyPage(result);setPickerError('')}}).catch(e=>{if(!controller.signal.aborted)setPickerError(e.message)})},250)
    return()=>{clearTimeout(timer);controller.abort()}
  },[kind,propertySearch,propertyOffset,scopeKey])
  useEffect(()=>{
    if(kind!=='bindings'||!values.property_key)return
    const controller=new AbortController();setChosenProperty(null)
    registryApi.detail('properties',values.property_key,JSON.parse(scopeKey),{signal:controller.signal}).then(result=>{if(!controller.signal.aborted)setChosenProperty(result.item||result)}).catch(e=>{if(!controller.signal.aborted)setPickerError(e.message)})
    return()=>controller.abort()
  },[kind,values.property_key,scopeKey])
  const properties=useMemo(()=>[...new Map([...initialProperties,...propertyPage.items,...(chosenProperty?[chosenProperty]:[]),...(item.property_key?[{id:item.property_key,label:item.property_key}]:[])].reverse().map(p=>[p.id,p])).values()],[initialProperties,propertyPage,chosenProperty,item.property_key])
  const ref=useDialogFocus(true,()=>{if(busy||reloading)return;if(discardOpen)setDiscardOpen(false);else requestClose()})
  const change=(key,value)=>setValues(v=>({...v,[key]:value,...(key==='property_key'?{profile_id:'',custom_output:false}:{})}))
  const field=(key,label,{area=false,required=false,disabled=false,type='text',hint}={})=><label className="rwb-field" key={key}><span>{label}</span>{area?<textarea name={key} value={values[key]??''} rows={3} disabled={disabled||busy} onChange={e=>change(key,e.target.value)} />:<input name={key} value={values[key]??''} type={type} disabled={disabled||busy} required={required} onChange={e=>change(key,e.target.value)} />}{hint&&<small>{hint}</small>}</label>
  const select=(key,label,options,{required=false,disabled=false}={})=><label className="rwb-field" key={key}><span>{label}</span><select name={key} value={values[key]??''} required={required} disabled={disabled||busy} onChange={e=>change(key,e.target.value)}><option value="">请选择</option>{values[key]&&!options.some(o=>o.id===values[key])&&<option value={values[key]}>{values[key]}（当前引用）</option>}{options.map(option=><option key={option.id} value={option.id}>{optionLabel(option,key)}</option>)}</select></label>
  const submit=async event=>{
    event.preventDefault();setError('')
    try {
      if(catalogLoading||catalogError)throw new Error('请先成功读取当前版本的完整类型与性质目录，输入内容已保留')
      const policy=(capabilities.conversion_policies||[]).find(p=>p.id===values.conversion_policy)
      const prepared={...values,...(policy?{conversion_policy_ref:policy.ref}:{})}
      const payload=registryEditorPayload(kind,prepared,item)
      if(kind==='properties'&&values.conversion_policy){const policy=(capabilities.conversion_policies||[]).find(p=>p.id===values.conversion_policy);if(policy){const selected=payload.output_profiles[Number(values.profile_index)||0];selected.conversion_policy_ref=policy.ref||policy.reference||{id:policy.id,version:policy.version,content_sha256:policy.content_sha256}}}
      if(kind==='bindings'){
        const property=chosenProperty?.id===values.property_key?chosenProperty:properties.find(p=>p.id===values.property_key)
        payload.profile_ref=registryBindingProfile(property,values.profile_id,item.property_key===values.property_key?item.profile_ref:null)
        if(values.custom_output){const baseline=property?.output_profiles?.find(p=>registryProfileKey(p)===values.profile_id)||item.output_profile;if(!baseline)throw new Error('请先读取当前类型输出方案的精确基础配置');payload.output_profile=registryOutputProfile(prepared,baseline)}
      }
      await onSave(payload)
    }catch(e){setError(e.message)}
  }
  const property=chosenProperty?.id===values.property_key?chosenProperty:properties.find(p=>p.id===values.property_key)
  return <div className="rwb-overlay rwb-editor-overlay" onMouseDown={e=>{if(e.target===e.currentTarget)requestClose()}}><section ref={ref} role="dialog" aria-modal="true" aria-labelledby="registry-editor-title" className="rwb-modal" tabIndex={-1}>
    <header><div><h3 id="registry-editor-title">{item.id?'编辑':'新增'}{REGISTRY_KINDS[kind]}草稿</h3><p>保存草稿 → 校验与影响 → 发布；仅发布后的新任务使用。</p></div><button type="button" aria-label="关闭编辑器" disabled={busy||reloading} onClick={requestClose}>×</button></header>
    {discardOpen&&<RegistryDiscardNotice noticeRef={discardRef} busy={busy||reloading} onContinue={()=>setDiscardOpen(false)} onDiscard={()=>{if(!busy&&!reloading)onClose()}}/>}
    {catalogLoading&&<p className="rwb-alert" role="status">正在读取当前版本的完整类型、分类与能力目录…</p>}
    {catalogError&&<div className="rwb-alert" role="alert">完整目录读取失败：{catalogError}。输入内容已保留。{onReloadCatalog&&<button type="button" onClick={onReloadCatalog}>重新读取完整目录</button>}</div>}
    {conflict&&<div className="rwb-alert" role="alert">服务器已有新版本。输入内容已保留；重新读取最新记录并核对后再保存。{onReload&&<button type="button" disabled={reloading} onClick={async()=>{setReloading(true);try{const latest=await onReload(kind,item);if(latest){setItem(latest);setServerReview(latest);setReviewed(false)}}catch(e){setError(e.message)}finally{setReloading(false)}}}>读取最新版本并保留输入</button>}</div>}
    {serverReview&&<div className="rwb-conflict-review"><strong>最新服务器记录 · r{serverReview.revision}</strong><p>{serverReview.label}：{serverReview.description}</p><details><summary>比较完整服务器记录</summary><pre>{JSON.stringify(serverReview,null,2)}</pre></details><label><input type="checkbox" checked={reviewed} onChange={e=>setReviewed(e.target.checked)}/>已核对保留的输入，同意以最新记录为基础保存</label></div>}
    <form onSubmit={submit}><div className="rwb-form-groups">
      <fieldset><legend>1 · 身份与命名</legend>
        {kind==='types'?<>{field('label','显示名称',{required:true})}{field('code','类型代码',{required:!item.id,disabled:!!item.id&&item.origin!=='user',hint:item.id&&item.origin!=='user'?'标准类型代码不可修改':'自定义类型代码与名称独立保存'})}{field('aliases','别名',{area:true})}</>:kind==='properties'?<>{field('label','性质显示名称',{required:true})}{field('property_id','性质 ID',{disabled:true,hint:'服务器分配性质 ID；以精确记录键区分定义版本'})}{field('quantity_key','科学量标识',{required:true,disabled:!!item.id,hint:'科学身份变更须新增性质'})}{field('quantity_kind','科学量种类',{disabled:!!item.id})}{field('aliases','别名',{area:true})}</>:<>{select('type_id','当前天体类型',types,{required:true})}<label className="rwb-field"><span>搜索精确性质记录</span><input type="search" value={propertySearch} onChange={e=>{setPropertySearch(e.target.value);setPropertyOffset(0)}} placeholder="按名称、别名搜索全部记录"/></label>{select('property_key','精确性质记录',properties.map(p=>({id:p.id,label:`${p.label||p.property_id} · ${p.id}`})),{required:true})}{select('profile_id','精确输出方案',(property?.output_profiles||[]).map(p=>({id:registryProfileKey(p),label:(p.label||p.profile_id||p.id)+String.fromCharCode(32)+p.version+String.fromCharCode(32)+p.content_sha256})))}<div className="rwb-picker-pages"><button type="button" disabled={!propertyOffset} onClick={()=>setPropertyOffset(n=>Math.max(0,n-25))}>上一组</button><span>{propertyPage.total} 条匹配</span><button type="button" disabled={propertyOffset+25>=propertyPage.total} onClick={()=>setPropertyOffset(n=>n+25)}>下一组</button></div>{pickerError&&<p role="alert">{pickerError}</p>}</>}
      </fieldset>
      <fieldset><legend>2 · 定义与适用范围</legend>
        {kind==='types'?<>{(!item.id||item.origin==='user')&&select('parent_id','父类型（沿父链继承一个标准锚点）',types.filter(t=>t.id!==item.id),{required:true})}{field('description','类型定义',{area:true})}</>:kind==='properties'?<>{field('description','科学定义',{area:true,required:true})}<RegistryFamilySelect className="rwb-field" families={families} value={values.family_id} onChange={value=>change('family_id',value)} disabled={busy||reloading} required emptyLabel="请选择性质分类"/>{select('subject_class_id','主体类别',capabilities.subjects||[],{required:true,disabled:!!item.id})}{select('scope','主体范围',[{id:'whole_object',label:'整体天体'},{id:'bounded_whole',label:'有界整体'},{id:'whole_system_relation',label:'整体系统关系'},{id:'target_environment_relation',label:'目标与环境关系'}],{required:true,disabled:!!item.id})}{select('value_kind','值类型',[{id:'real',label:'实数'},{id:'integer',label:'整数'},{id:'text',label:'文本'},{id:'boolean',label:'布尔'},{id:'category',label:'类别'},{id:'relation',label:'关系'}],{disabled:!!item.id})}{values.value_kind==='category'&&field('categories','类别代码与含义',{area:true,required:true,disabled:!!item.id,hint:'每行填写：代码=科学含义'})}{values.value_kind==='relation'&&<>{field('predicate_id','关系谓词',{required:true,disabled:!!item.id})}{field('subject_role','主体角色',{required:true,disabled:!!item.id})}{field('object_role','关联对象角色',{required:true,disabled:!!item.id})}</>}</>:<><p>仅修改当前类型的适用绑定；共享性质定义不受此操作修改。</p>{field('display_order','显示顺序',{type:'number'})}</>}
      </fieldset>
      <fieldset><legend>3 · 输出单位与表述</legend>{kind==='properties'&&item.id&&!item.output_profiles?.length&&<label className='rwb-field rwb-binding-override'><span><input type='checkbox' checked={!!values.create_profile} onChange={e=>change('create_profile',e.target.checked)}/>为此定义添加输出方案</span><small>当前来源没有输出方案。新增配置后，可在“处理与验证”中检查其可用范围。</small></label>}{kind==='bindings'&&<label className='rwb-field rwb-binding-override'><span><input type='checkbox' checked={values.custom_output} disabled={busy||!property} onChange={e=>{const enabled=e.target.checked;if(!enabled){setValues(v=>({...v,custom_output:false,profile_id:property?.output_profiles?.[0]?registryProfileKey(property.output_profiles[0]):''}));return}const baseline=property?.output_profiles?.find(p=>registryProfileKey(p)===values.profile_id)||item.output_profile||property?.output_profiles?.[0];const output=registryEditorValues('properties',{output_profiles:baseline?[baseline]:[]});const keys=['unit','dimension','unit_kind','unit_semantic_kind','parser_format','parser_version','representation_kind','representation_scale','representation_offset','reference_value','reference_unit','native_coordinate_only','system_id','system_version','system_hash','coordinate_meaning','scale_id','conversion_policy'];setValues(v=>({...v,...Object.fromEntries(keys.map(k=>[k,output[k]])),custom_output:true}))}}/>为当前类型自定义输出配置</span><small>仅保存当前类型绑定的单位与表述配置；共享性质定义保持原内容，自动转换资格将重新核验。</small></label>}
        {(kind==='properties'&&(!item.id||item.output_profiles?.length||values.create_profile)||kind==='bindings'&&values.custom_output)?<>{item.output_profiles?.length>1&&<label className="rwb-field"><span>编辑输出方案</span><select value={values.profile_index} onChange={e=>{const index=Number(e.target.value),next=registryEditorValues(kind,{...item,output_profiles:[item.output_profiles[index]]});const keys=['unit','dimension','unit_kind','unit_semantic_kind','parser_format','parser_version','representation_kind','representation_scale','representation_offset','reference_value','reference_unit','native_coordinate_only','system_id','system_version','system_hash','coordinate_meaning','scale_id','conversion_policy'];setValues(v=>({...v,...Object.fromEntries(keys.map(k=>[k,next[k]])),profile_index:index}))}}>{item.output_profiles.map((p,index)=><option key={p.profile_id||p.id||index} value={index}>{p.label||p.profile_id||p.id||`方案 ${index+1}`}</option>)}</select></label>}{select('scale_id','对象尺度',capabilities.scales||[],{required:true})}{select('unit_kind','单位种类',[{id:'physical',label:'物理单位'},{id:'dimensionless',label:'无量纲'},{id:'not_applicable',label:'不适用（非数值）'}])}{values.unit_kind!=='not_applicable'&&<>{field('unit','目标单位',{required:values.unit_kind==='physical'})}{field('dimension','量纲',{required:values.unit_kind==='physical'})}</>}{values.unit_kind==='physical'&&<>{select('parser_format','单位解析格式',[{id:'generic',label:'通用格式'},{id:'cds',label:'CDS'},{id:'vounit',label:'VOUnit'},{id:'source_literal',label:'来源原文'}])}{field('parser_version','单位解析版本标识',{required:true,hint:'此字段只记录配置，不代表软件资格已验证'})}</>}{values.unit_kind==='dimensionless'&&field('unit_semantic_kind','无量纲科学含义',{required:true})}{select('representation_kind','表述方式',[{id:'linear',label:'线性'},{id:'log10',label:'以 10 为底的对数'},{id:'ln',label:'自然对数'},{id:'magnitude',label:'星等'},{id:'category',label:'类别'},{id:'text',label:'文本'},{id:'boolean',label:'布尔'},{id:'relation',label:'关系'}])}{field('representation_scale','表述比例')}{field('representation_offset','表述偏移')}{['log10','ln','magnitude'].includes(values.representation_kind)&&<>{field('reference_value','参考值',{required:!values.native_coordinate_only})}{field('reference_unit','参考单位',{required:!values.native_coordinate_only})}<label className="rwb-field"><span><input type="checkbox" checked={values.native_coordinate_only} onChange={e=>change('native_coordinate_only',e.target.checked)}/>仅保留来源坐标</span><small>无精确许可时不执行自动转换；星等系统等额外约束由服务器校验。</small></label></>}{values.representation_kind==='magnitude'&&<>{field('system_id','测光系统精确引用 ID',{required:!values.native_coordinate_only})}{field('system_version','测光系统引用版本',{required:!values.native_coordinate_only})}{field('system_hash','测光系统内容指纹',{required:!values.native_coordinate_only})}</>}{field('coordinate_meaning','输出值含义',{area:true})}{select('conversion_policy','已有转换策略',capabilities.conversion_policies||[],{required:!item.id})}<p className="rwb-caution">保存后按准确的定义、输出配置与验证结果确定处理范围；无法转换的来源数据保留原值与原因。</p></>:kind==='types'?field('color','分类配色（可选配置）',{hint:'用户配色作为配置数据；留空沿用系统主题'}):<p>输出方案由精确 profile 引用确定；选择已有方案，不运行自定义科学脚本。</p>}
      </fieldset>
      {kind==='properties'&&(capabilities.user_execution_protocol||item.execution_capabilities)&&<fieldset><legend>处理与验证</legend>
        {item.id?<><p>以下为服务器已保存记录的处理能力；当前编辑内容保存并重新校验后生效。</p><RegistryExecutionStatus capabilities={item.execution_capabilities} legacyReady={item.automatic_conversion_ready}/></>:<p>新定义会分别校验检索、提取、原值保留和规范化能力。技术验证不改变来源的科学审核标识。</p>}
        <RegistryExecutionExamples value={values.execution_examples} onChange={value=>change('execution_examples',value)} busy={busy||reloading}
          targetUnit={Number(values.profile_index)===0?values.unit:item.output_profiles?.[0]?.unit?.canonical_symbol}
          profiles={[...(item.output_profiles||[]),...(item.bindings||[]).flatMap(binding=>binding.output_profile?[binding.output_profile]:[])]}
          numeric={['real','integer'].includes(values.value_kind)}/>
        <p>样例可留空以使用原值保留模式。保存后重新校验当前草稿；未保存输入不会被标记为已验证。</p>
      </fieldset>}
      <fieldset><legend>4 · 适用条件与状态</legend>
        {kind!=='properties'?<><ConditionEditor title="适用条件" value={values.conditions} onChange={v=>change('conditions',v)} types={types} subjects={capabilities.subjects||[]} busy={busy}/>{kind==='bindings'&&<ConditionEditor title="排除条件" value={values.excluded_conditions} onChange={v=>change('excluded_conditions',v)} types={types} subjects={capabilities.subjects||[]} busy={busy}/>}</>:<p>适用条件在当前类型绑定中独立维护；修改共享定义将检查所有类型依赖。</p>}
        {select('status','状态',[{id:'active',label:'启用'},{id:'disabled',label:'禁用'}])}
      </fieldset>
      <fieldset><legend>5 · 来源依据与变更说明</legend>{field('source_note','来源与理由',{area:true,required:true,hint:'说明依据、单位表述及范围变化；不填写伪造的科学审查或软件资格回执'})}<p>关联理论映射由服务端检查；精确未变映射可复用已审计溯源，变更映射会暂停并显示原因。</p></fieldset>
    </div>{error&&<p role="alert" className="rwb-alert">{error}</p>}<footer><button type="button" onClick={requestClose} disabled={busy||reloading}>取消</button><button type="submit" className="rwb-primary" disabled={busy||conflict||reloading||catalogLoading||!!catalogError||(serverReview&&!reviewed)}>{busy?'正在保存…':'保存草稿'}</button></footer></form>
  </section></div>
}
