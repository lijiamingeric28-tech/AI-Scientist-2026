import { useEffect, useState } from 'react'
import * as api from '@/services/api'
export default function LibraryStatus({active}) {
 const [status,setStatus]=useState(null),[error,setError]=useState('')
 useEffect(()=>{if(!active)return;let disposed=false;api.getLibraryStatus().then(v=>{if(!disposed)setStatus(v)}).catch(e=>{if(!disposed)setError(e.message)});return()=>{disposed=true}},[active])
 return <section className="settings-group"><h3>科学库与知识库</h3>{error?<p role="alert">{error}</p>:!status?<p>正在读取发布状态…</p>:<><p>性质库：{status.registry?.state==='available'?'已安装':`不可用（${status.registry?.reason||'未记录'}）`}</p><p>知识库：{status.knowledge_bindings?.state==='available'?'已安装':`不可用（${status.knowledge_bindings?.reason||'未记录'}）`}</p>{status.knowledge_content?.state==='available'&&Number.isFinite(status.knowledge_content.entries)&&Number.isFinite(status.knowledge_content.types)&&<p>{status.knowledge_content.entries} 张知识卡，覆盖 {status.knowledge_content.types} 类；{status.knowledge_bindings.bindings} 项性质绑定。</p>}</>}</section>
}
