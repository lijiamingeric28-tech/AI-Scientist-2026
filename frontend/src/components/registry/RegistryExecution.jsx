import {executionCapabilityRows,executionCapabilityText,executionCheckText} from '@/lib/registryExecution'
import {registryProfileKey,registryProfileRef} from '@/lib/registryWorkbench'

const states = {passed:'已通过',failed:'未通过',pending:'待验证',ready:'可用',not_run:'未执行',skipped:'未执行'}

export function RegistryExecutionStatus({capabilities,legacyReady=false}) {
  if (!capabilities) return <p className="rwb-caution">{executionCapabilityText(null,legacyReady)}；此版本沿用原有执行范围。</p>
  const validation=capabilities.validation||{},checks=validation.checks||[],examples=validation.examples||[]
  return <div className="rwb-execution-status">
    <p><strong>{capabilities.origin==='builtin'?'内置定义':capabilities.origin==='user_modified'?'用户修改':'用户定义'}</strong> · {executionCapabilityText(capabilities)}</p>
    <dl className="rwb-execution-capabilities">{executionCapabilityRows(capabilities).map(row=><div key={row.key}>
      <dt>{row.label}</dt><dd><span className={row.ready?'is-ready':''}>{row.ready?'可用':'未开放'}</span>
        {row.reasons.map((reason,index)=><p key={index}>{executionCheckText(reason)}</p>)}</dd>
    </div>)}</dl>
    <p>技术验证：{states[validation.state]||'待验证'}。验证记录检查软件行为，保留原有科学审核状态。</p>
    {checks.length>0&&<ul className="rwb-value-list">{checks.map((check,index)=><li key={index}>{executionCheckText(check)}{check.state?` · ${states[check.state]||check.state}`:''}</li>)}</ul>}
    {examples.length>0&&<details><summary>样例验证结果（{examples.length}）</summary><ul className="rwb-value-list">{examples.map((example,index)=><li key={index}>
      {example.label||`样例 ${index+1}`} · {states[example.state]||(example.passed===true?'已通过':example.passed===false?'未通过':'查看验证记录')}
      {example.actual_value!==undefined&&<span> · 实际输出 {String(example.actual_value)}</span>}
      {example.expected_value!==undefined&&<span> · 预期 {String(example.expected_value)}</span>}
      {(example.message||example.reason)&&<p>{example.message||example.reason}</p>}
    </li>)}</ul></details>}
    {capabilities.execution_ref&&<details className="rwb-technical"><summary>固定执行版本</summary><code>{capabilities.execution_ref.id} · v{capabilities.execution_ref.version}<br/>{capabilities.execution_ref.content_sha256}</code></details>}
  </div>
}

export function RegistryExecutionReport({report}) {
  if(!report)return null
  const entries=Object.entries(report.properties||{}).filter(([,capability])=>capability.origin!=='builtin')
  return <section className="rwb-execution-status" aria-label="处理能力验证结果">
    <p>用户定义与修改：{entries.length} 项。内置性质沿用原有精确执行范围。</p>
    {entries.map(([key,capability])=><details key={key}><summary>{capability.label||key} · {executionCapabilityText(capability)}</summary><RegistryExecutionStatus capabilities={capability}/></details>)}
    {report.manifest&&<details className="rwb-technical"><summary>执行清单引用 · 技术记录</summary><pre>{JSON.stringify({schema_version:report.manifest.schema_version,content_sha256:report.manifest.content_sha256,
      total:Object.keys(report.manifest.contracts||{}).length,references:Object.values(report.manifest.contracts||{}).slice(0,100).map(entry=>entry.reference)},null,2)}</pre></details>}
  </section>
}

export function RegistryPublishReview({workspace,validation,activeBundle}) {
  const coverage=validation?.knowledge_coverage,changed=validation?.impact?.changed
  return <section className="rwb-execution-status" aria-label="本次发布摘要">
    <dl className="rwb-facts">
      <div><dt>草稿修订</dt><dd>r{workspace?.revision??validation?.workspace_revision??'—'}</dd></div>
      <div><dt>校验状态</dt><dd>{states[validation?.state]||'待验证'}</dd></div>
      <div><dt>生效范围</dt><dd>发布后创建的新任务；历史任务保留固定版本。</dd></div>
      {changed!=null&&<div><dt>变更记录</dt><dd>{Array.isArray(changed)?changed.length:String(changed)}</dd></div>}
      {coverage&&<div><dt>洞察知识覆盖</dt><dd>可用 {coverage.available??'—'} · 缺少 {coverage.missing??'—'}；缺少解释知识仍保留测量与出处。</dd></div>}
    </dl>
    <RegistryExecutionReport report={validation?.execution}/>
    {(validation?.warnings||[]).length>0&&<ul className="rwb-value-list">{validation.warnings.map((warning,index)=><li key={index}>{executionCheckText(warning)}</li>)}</ul>}
    <details className="rwb-technical"><summary>本次发布的版本引用</summary><pre>{JSON.stringify({workspace_id:workspace?.id,workspace_revision:workspace?.revision,
      validation_id:validation?.id,validated_projection:validation?.projection_sha256,expected_active_bundle_id:activeBundle?.id},null,2)}</pre></details>
  </section>
}

export function RegistryExecutionExamples({value='[]',onChange,busy=false,targetUnit='',numeric=true,profiles=[]}) {
  let examples
  try { examples=JSON.parse(value||'[]');if(!Array.isArray(examples))examples=[] }
  catch { return <p role="alert">验证样例格式有误，原输入已保留，请重新读取记录后核对。</p> }
  if(!numeric)return <p>此性质按既有值结构验证并保留原值，无需填写数值换算样例。</p>
  const targets=[...new Map(profiles.filter(profile=>profile.profile_id||profile.id||profile.ref).map(profile=>[registryProfileKey(profile),profile])).values()]
  const update=list=>onChange(JSON.stringify(list))
  const change=(index,key,next)=>update(examples.map((example,i)=>i===index?{...example,[key]:next}:example))
  const representation=(index,key,next)=>change(index,'source_representation',{...examples[index].source_representation,[key]:next})
  const field=(index,key,label,example=examples[index])=><label className="rwb-field"><span>{label}</span><input type="text" aria-label={`样例 ${index+1} ${label}`} value={example[key]??''} disabled={busy} onChange={event=>change(index,key,event.target.value)}/></label>
  const repField=(index,key,label)=><label className="rwb-field"><span>{label}</span><input type="text" aria-label={`样例 ${index+1} ${label}`} value={examples[index].source_representation?.[key]??''} disabled={busy} onChange={event=>representation(index,key,event.target.value)}/></label>
  return <div className="rwb-execution-examples">
    <p>目标输出单位：{targetUnit||'按输出配置'}。填写已知来源值和预期输出，保存草稿后通过“校验与发布”运行验证。未填写样例时，可用范围由服务端分别判断。</p>
    {examples.map((example,index)=><article key={index} className="rwb-execution-example">
      <header><strong>验证样例 {index+1}</strong><button type="button" disabled={busy} onClick={()=>update(examples.filter((_,i)=>i!==index))}>移除样例</button></header>
      <div className="rwb-example-fields">{field(index,'label','样例名称')}{field(index,'source_value','来源值')}{field(index,'source_unit','来源单位')}{field(index,'expected_value','预期输出值')}
        {(targets.length>1||example.profile_ref)&&<label className="rwb-field"><span>样例目标输出方案</span><select aria-label={`样例 ${index+1} 样例目标输出方案`} disabled={busy} value={example.profile_ref?registryProfileKey(example.profile_ref):''} onChange={event=>{
          const next={...example};const target=targets.find(profile=>registryProfileKey(profile)===event.target.value)
          if(target)next.profile_ref=registryProfileRef(target);else delete next.profile_ref
          update(examples.map((old,i)=>i===index?next:old))
        }}><option value="">默认首个共享输出方案{targetUnit?` · ${targetUnit}`:''}</option>
          {targets.map(profile=><option key={registryProfileKey(profile)} value={registryProfileKey(profile)}>{profile.label||profile.profile_id||profile.id} · {profile.unit?.canonical_symbol||profile.unit?.kind||'按配置'} · v{registryProfileRef(profile).version} · {registryProfileRef(profile).content_sha256}</option>)}
          {example.profile_ref&&!targets.some(profile=>registryProfileKey(profile)===registryProfileKey(example.profile_ref))&&<option value={registryProfileKey(example.profile_ref)} disabled>已保存引用 {example.profile_ref.id} · 当前目录未提供，请核对版本</option>}
        </select></label>}
        <label className="rwb-field"><span>来源表示方式</span><select aria-label={`样例 ${index+1} 来源表示方式`} value={example.source_representation?.kind||'linear'} disabled={busy} onChange={event=>representation(index,'kind',event.target.value)}>
          <option value="linear">线性</option><option value="log10">以 10 为底的对数</option><option value="ln">自然对数</option><option value="magnitude">星等</option>
        </select></label>
        {['log10','ln','magnitude'].includes(example.source_representation?.kind)&&<>{repField(index,'reference_value','来源参考值')}{repField(index,'reference_unit','来源参考单位')}</>}
      </div>
      <details><summary>来源表示参数</summary><div className="rwb-example-fields">{repField(index,'scale','来源比例')}{repField(index,'offset','来源偏移')}
        {example.source_representation?.kind==='magnitude'&&['id','version','content_sha256'].map(key=><label className="rwb-field" key={key}><span>{({id:'来源测光系统 ID',version:'来源测光系统版本',content_sha256:'来源测光系统内容指纹'})[key]}</span><input type="text" value={example.source_representation.system_ref?.[key]??''} disabled={busy} onChange={event=>representation(index,'system_ref',{...example.source_representation.system_ref,[key]:event.target.value})}/></label>)}
      </div></details>
      {example.profile_ref&&<small>此样例绑定输出方案 {example.profile_ref.id} · v{example.profile_ref.version}。</small>}
    </article>)}
    <button type="button" disabled={busy||examples.length>=20} onClick={()=>update([...examples,{label:`样例 ${examples.length+1}`,source_value:'',source_unit:'',source_representation:{kind:'linear'},expected_value:''}])}>添加验证样例</button>
    <small>数值按原始十进制文本保存。样例验证不授予科学审核标识；无法转换的实际来源数据仍保留原值与原因。</small>
  </div>
}
