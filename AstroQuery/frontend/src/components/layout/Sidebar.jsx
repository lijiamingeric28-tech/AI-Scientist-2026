import { useState } from 'react'
import { queryKey, sidebarIdentity } from '@/hooks/useSidebarIdentity'
import { Icon } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { STATUS_LABELS } from '@/components/status'

const FILTERS=[['all','全部'],['active','进行中'],['attention','待我处理'],['ended','已结束'],['completed','已完成'],['cancelled','已取消'],['error','异常结束']]
const relative=iso=>{if(!iso||!Number.isFinite(Date.parse(iso)))return '历史归档'; const n=Math.max(0,Math.floor((Date.now()-Date.parse(iso))/60000));return n<60?`${n}分钟前`:n<1440?`${Math.floor(n/60)}小时前`:new Date(iso).toLocaleDateString('zh-CN') }
export default function Sidebar({playbackActive,currentPresentation,tasks,loadingTasks,total,selectedId,onSelect,onNew,onCollapse,onReplay,onOpenHelp,onOpenSettings,onLoadMore,filter,onFilterChange,onDeleteTask,onBatchDelete,mode='user',onModeChange,demos=[]}) {
 const [manage,setManage]=useState(false),[checked,setChecked]=useState(new Set())
 const toggle=id=>setChecked(previous=>{const n=new Set(previous);n.has(id)?n.delete(id):n.add(id);return n})
 const rows=mode==='sample'?demos:tasks
 const activeIdentity = !playbackActive && sidebarIdentity(currentPresentation)
 return <aside className="sidebar-v1" aria-label="任务导航">
  <div className="sidebar-top"><Button className="new-query" onClick={onNew}><Icon.Plus aria-hidden="true"/> 新建查询</Button><Button variant="ghost" size="icon" onClick={onCollapse} aria-label="收起侧栏"><Icon.ChevronLeft /></Button></div>
  <div className="sidebar-modes">{[['user','我的查询'],['sample','演示样例']].map(([key,label])=><button className={mode===key?'active':''} key={key} onClick={()=>{setManage(false);setChecked(new Set());onModeChange(key)}}>{label}</button>)}</div>
  {mode==='user' && <><select className="sidebar-filter" aria-label="任务状态筛选" value={filter} onChange={e=>onFilterChange(e.target.value)}>{FILTERS.map(([key,label])=><option key={key} value={key}>{label}</option>)}</select><div className="sidebar-top"><span className="hint">{total} 项查询</span><button className="text-link" onClick={()=>{setManage(!manage);setChecked(new Set())}}>{manage?'取消管理':'管理'}</button></div></>}
  {manage && <div className="sidebar-top"><label><input type="checkbox" checked={rows.length>0&&rows.every(t=>checked.has(t.task_id))} onChange={e=>setChecked(new Set(e.target.checked?rows.map(t=>t.task_id):[]))}/> 当前已加载范围</label><p className="hint">已选 {checked.size} 项</p><Button variant="outline" disabled={!checked.size} onClick={()=>onBatchDelete([...checked])}>批量整删…</Button></div>}
  <div className="sidebar-tasks" >{mode==='sample'&&!rows.length?<p className="hint">演示样例待选定。可先浏览我的查询。</p>:<>
   {loadingTasks&&!rows.length && <p role="status">正在读取查询…</p>}
   {!loadingTasks&&!rows.length && <p className="hint">当前筛选没有查询。</p>}
   {rows.map(t=>{
    const meta = mode === 'user' && ((activeIdentity && t.task_id === currentPresentation?.task_id && activeIdentity) || t.display_identity)
    const title=(meta && (!meta.question || t.title===meta.question)) ? meta.target : t.title || t.query
    return <div key={t.task_id} data-task-id={t.task_id} data-query-ref={queryKey(t) || undefined} className={`task-list-row${t.task_id===selectedId?' selected':''}`}>
    {manage && <input aria-label={`选择任务：${t.title}`} type="checkbox" checked={checked.has(t.task_id)} onChange={()=>toggle(t.task_id)}/>}
    <button className="task-list-entry" aria-current={t.task_id===selectedId?'page':undefined} title={meta?.question || t.title || t.query} onClick={()=>onSelect(t.task_id)}><strong>{title}</strong>{meta?.properties && <span className="task-subjects">{meta.properties}</span>}<small>{STATUS_LABELS[t.status]||t.status} · {relative(t.created_at)}{t.created_at && <time dateTime={t.created_at}> · {new Date(t.created_at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false})}</time>}</small></button>
    {!manage && <div className="task-row-actions">{['completed','cancelled','error','failed'].includes(t.status)&&<button title="只读回放" aria-label={`回放：${t.title}`} onClick={()=>onReplay(t.task_id)}><Icon.Play /></button>}{mode!=='sample'&&<button title="清理或删除任务" aria-label={`管理：${t.title}`} onClick={()=>onDeleteTask(t)}><Icon.Ellipsis /></button>}</div>}
   </div>})}
   {mode==='user'&&rows.length<total && <Button variant="outline" onClick={onLoadMore}>加载下一页</Button>}
  </>}</div>
  <div className="sidebar-bottom"><Button variant="ghost" onClick={onOpenSettings}>设置</Button><Button variant="ghost" onClick={onOpenHelp}>使用帮助</Button></div>
 </aside>
}
