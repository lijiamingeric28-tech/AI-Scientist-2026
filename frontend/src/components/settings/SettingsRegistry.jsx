import {useEffect,useState} from 'react'
import {registryApi} from '@/hooks/useRegistryWorkbench'
import {Button} from '@/components/ui/button'
import '@/components/registry/registryWorkbench.css'

export default function SettingsRegistry({active,onLaunchStudio}) {
  const [summary,setSummary]=useState(null),[error,setError]=useState('')
  useEffect(()=>{if(!active)return;const controller=new AbortController();registryApi.summary({projection:'stats'}, {signal:controller.signal}).then(data=>{setSummary(data);setError('')}).catch(e=>{if(!controller.signal.aborted)setError(e.message)});return()=>controller.abort()},[active])
  return <div className="settings-panel-container rwb-settings-panel"><div className="settings-panel-intro"><h3 className="settings-panel-title">天体与性质规范</h3><p className="settings-panel-desc">按天体类型维护共享性质定义、输出单位与适用绑定，查看精确版本、科研洞察覆盖和变更依赖。</p></div><section className="settings-config-section"><div className="settings-config-section-header"><span className="settings-config-section-title">当前发布组合</span><span className="settings-config-section-badge">{error?'读取异常':summary?'已读取真实规范':'正在读取'}</span></div>{error&&<p className="resource-error" role="alert">{error}</p>}<div className="rwb-settings-metrics">{[['types','天体类型'],['properties','精确性质定义'],['bindings','类型适用绑定']].map(([key,title])=><div key={key}><strong>{summary?.counts?.[key]??'—'}</strong><span>{title}</span></div>)}</div><p className="settings-panel-desc">活动版本：{summary?.active_bundle?.id||'尚未读取'}。发布与历史版本只读；修改先保存服务器草稿，再校验影响、发布与激活。仅新任务使用新版本。</p></section><div><Button variant="accent" onClick={onLaunchStudio}>打开规范工作台 →</Button></div><p className="settings-panel-desc">自定义类型沿一个父链连接到标准类型。用户定义不自动获得科学审核、模型执行或转换资格；不满足精确能力范围时保留来源数据。</p></div>
}
