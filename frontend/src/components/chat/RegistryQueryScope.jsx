import { Button } from '@/components/ui/button'
import {executionCapabilityText} from '@/lib/registryExecution'
import './registryQueryScope.css'

export default function RegistryQueryScope({ draft, question, sending, submit }) {
  const choices = question.user_type_choices || []
  const bundle = question.registry_bundle || draft.registry_bundle
  const gaps = (question.capability_gaps || []).filter(gap => gap.automatic_execution_ready === false)
  const custom = (question.property_catalog?.bindings || question.preview?.properties || []).filter(binding => binding.execution_capabilities && binding.execution_capabilities.origin!=='builtin')
  if (!bundle && !choices.length && !gaps.length && !custom.length) return null
  return <section className="registry-query-scope" aria-label="本次规范范围">
    <div className="registry-query-version"><span>本次固定规范</span>
      <code title={bundle?.registry_ref?.id}>{bundle?.registry_ref?.id || draft.registry_release?.id || '原固定版本'}</code>
      <Button variant="ghost" disabled={sending} onClick={() => submit({ type: 'reload_registry' })}>升级规范并重新确认</Button>
    </div>
    {choices.length > 0 && <label className="registry-query-subtype">用户指定子类
      <select aria-label="用户指定子类" disabled={sending} value={question.user_type_ref?.id || ''}
        onChange={event => submit({ type: 'select_user_type', type_id: event.target.value || null })}>
        <option value="">沿用已确认标准类型</option>
        {choices.map(choice => <option key={choice.id} value={choice.id}>{choice.label}</option>)}
      </select><small>SIMBAD 原始类型：{draft.target?.primary_otype}。此选择只补充本任务的用户分类。</small>
    </label>}
    {gaps.length > 0 && <details className="registry-query-gaps"><summary>{gaps.length} 项性质自动处理未就绪</summary>
      <p>这些用户定义尚无准确匹配的科学许可或执行验证，暂不进入自动检索和转换；其他已就绪性质可继续使用。</p>
      <ul>{gaps.map((gap, index) => <li key={gap.binding_id || `${gap.property_id}:${index}`}>{gap.label || gap.property_id} · 保留定义，等待能力匹配</li>)}</ul>
    </details>}
    {custom.length > 0 && <details className="registry-query-gaps"><summary>用户定义处理范围（{custom.length}）</summary>
      <p>使用本任务固定版本的定义和执行验证。无法转换的来源数据保留原值、单位、误差与出处。</p>
      <ul>{custom.map(binding=><li key={binding.property_id}>{binding.display_name||binding.definition?.name_cn||binding.property_id} · {executionCapabilityText(binding.execution_capabilities)}
        {(binding.execution_capabilities.normalization?.reasons||[]).map((reason,index)=><p key={index}>{typeof reason==='string'?reason:reason.message||reason.reason}</p>)}
      </li>)}</ul>
    </details>}
  </section>
}
