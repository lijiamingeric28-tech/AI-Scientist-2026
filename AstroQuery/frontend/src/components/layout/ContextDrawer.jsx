import KnowledgeDetail from '@/components/results/KnowledgeDetail'
import ResearchFigure from '@/components/results/ResearchFigure'
import { getRecord } from '@/services/api'
import { useLayoutEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import SourceDetails from '@/components/results/SourceDetails'
import RecordDetail from '@/components/results/RecordDetail'
import { Excerpt } from '@/components/results/ReadableContent'
import StageDetailPanel from '@/components/workflow/StageDetailPanel'
import { buildDupIndex } from '@/lib/dupMarkers'
import { sourceName, readableText, SOURCE_TYPES } from '@/lib/readableData'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import { useDismissTransition } from '@/hooks/useDismissTransition'
import { useContentTransition } from '@/hooks/useContentTransition'

export default function ContextDrawer({ detail, data, pipeline, onClose, onChange, onShowStageInChat, onOpenResults }) {
  const [width, setWidth] = useState(620), [available, setAvailable] = useState(window.innerWidth)
  const [history, setHistory] = useState([])
  const navigation = useRef(null)
  const currentDetail=useRef(detail);currentDetail.current=detail
  const [loadError,setLoadError]=useState('')
  const direction = useRef(1)
  const overlay = available - width < 520
  const dismissal = useDismissTransition(onClose, { duration: 160, active: !!detail, identity: detail })
  const ref = useDialogFocus(!!detail, dismissal.close, { trap: overlay })
  useLayoutEffect(() => {
    const next = navigation.current
    navigation.current = null
    if (!next || next.detail !== detail) {
      setHistory(previous => previous.length ? [] : previous)
    }
    if (!detail || !ref.current) return
    const restoring = next?.detail === detail ? next : null
    for (const element of ref.current.querySelectorAll('details')) {
      if (restoring?.expanded?.includes(element.dataset.disclosureKey || element.querySelector('summary')?.textContent)) element.open = true
    }
    const scroller = ref.current.querySelector('.record-detail-body, .context-content')
    if (scroller) scroller.scrollTop = restoring?.scrollTop || 0
    if (restoring) {
      const origin = [...ref.current.querySelectorAll('[data-detail-action]')].find(element => element.getAttribute('data-detail-action') === restoring.focusKey)
      ;(origin || ref.current.querySelector('[data-detail-heading]') || ref.current)?.focus({ preventScroll: true })
    }
  }, [detail])
  useLayoutEffect(() => {
    const parent = ref.current?.closest('.task-workspace') || document.querySelector('.task-workspace')
    if (!parent) return
    setAvailable(parent.clientWidth)
    const observer = new ResizeObserver(entries => setAvailable(entries[0].contentRect.width))
    observer.observe(parent)
    return () => observer.disconnect()
  }, [])
  useContentTransition(ref, detail ? `${detail.type}:${detail.record?.record_id || detail.source?.source_id || detail.stageId}:${detail.agentKey || ''}` : '', { active: Boolean(detail), selector: '.record-detail-body, .context-content', axis: 'x', distance: 16 * direction.current, duration: 240 })
  if (!detail) return null
  const navigate = async next => {
    const previousDetail=detail
    if(next.type==='record'&&next.record.details_loaded===false){try{const r=next.record;next={...next,record:await getRecord(r.source.task_id,r.delivery_id,r.delivery_revision,r.record_id)}}catch(e){setLoadError(e.message);return}if(currentDetail.current!==previousDetail)return}
    setLoadError('')
    direction.current = 1
    const scroller = ref.current?.querySelector('.record-detail-body, .context-content')
    const expanded = [...(ref.current?.querySelectorAll('details[open]') || [])].map(element => element.dataset.disclosureKey || element.querySelector('summary')?.textContent)
    setHistory(previous => [...previous, { detail, scrollTop: scroller?.scrollTop || 0, expanded, focusKey: document.activeElement?.getAttribute('data-detail-action') }])
    navigation.current = { detail: next, scrollTop: 0 }
    onChange(next)
  }
  const goBack = () => {
    const previous = history.at(-1)
    if (!previous) return
    direction.current = -1
    setHistory(items => items.slice(0, -1))
    navigation.current = previous
    onChange(previous.detail)
  }
  const quality = data.resources.quality.data
  const records = data.resources.records.data || [], sources = data.resources.sources.data || []
  const stage = pipeline.stages.find(item => item.id === detail.stageId) || detail.stage
  const dup = detail.type === 'record' ? buildDupIndex(records, quality?.quality_report).byRecordId[detail.record.record_id] : null
  const startResize = event => {
    event.preventDefault()
    const x = event.clientX, startWidth = width
    event.currentTarget.setPointerCapture(event.pointerId)
    const move = e => setWidth(Math.min(900, Math.max(440, startWidth + x - e.clientX)))
    const el = event.currentTarget
    const stop = () => { el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', stop); el.removeEventListener('pointercancel', stop); el.removeEventListener('lostpointercapture', stop) }
    el.addEventListener('pointermove', move); el.addEventListener('pointerup', stop); el.addEventListener('pointercancel', stop); el.addEventListener('lostpointercapture', stop)
  }
  const gallery=(data.resources.figures?.data||[]).filter(f=>!detail.figure?.galleryIds||detail.figure.galleryIds.includes(f.figure_id))
  const figureIndex=gallery.findIndex(f=>f.figure_id===detail.figure?.figure_id)
  const moveFigure=step=>navigate({type:'figure',figure:{...gallery[(figureIndex+step+gallery.length)%gallery.length],galleryIds:detail.figure?.galleryIds}})
  const source = detail.source
  const authors = Array.isArray(source?.authors) ? source.authors.map(readableText).filter(Boolean) : []
  return <>
    {overlay && <div className="context-backdrop" data-closing={dismissal.closing || undefined} onClick={dismissal.close} />}
    <aside ref={ref} data-closing={dismissal.closing || undefined} onAnimationEnd={dismissal.onAnimationEnd} onKeyDownCapture={dismissal.onKeyDownCapture} role="dialog" aria-modal={overlay ? 'true' : undefined} aria-label="上下文详情" tabIndex={-1} className={`context-drawer animate-drawer-in${overlay ? ' overlay' : ''}`} style={{ width: overlay ? Math.min(width, window.innerWidth - 24) : width, flexBasis: overlay ? undefined : width }}>
      {!overlay && <div className="drawer-resize" onPointerDown={startResize} />}
      {loadError&&<p className="resource-error">{loadError}</p>}
      {history.length > 0 && <div className="drawer-back-row"><Button variant="ghost" size="sm" onClick={goBack}>← 返回上一项</Button></div>}
      {detail.type === 'loading-record' ? <><header className="record-detail-heading"><strong>{detail.record.field_name}</strong><Button variant="ghost" onClick={dismissal.close}>关闭</Button></header>
        <section className="context-content" aria-busy="true"><p className="record-measurement">{detail.record.field_value} {detail.record.field_unit}</p><p role="status">正在读取原件与处理记录…</p></section></> : detail.type === 'figure' ? <><header className="settings-header"><h2>研究图像</h2><Button variant="ghost" onClick={dismissal.close}>关闭</Button></header><ResearchFigure onPrevious={gallery.length>1?()=>moveFigure(-1):undefined} onNext={gallery.length>1?()=>moveFigure(1):undefined} figure={detail.figure} sources={sources} onOpenSource={source=>navigate({type:'source',source})}/></> : detail.type === 'knowledge' ? <KnowledgeDetail block={detail.block} onClose={dismissal.close}/> : detail.type === 'record' ? <RecordDetail key={detail.record.record_id} embedded record={detail.record} quality={quality} sources={sources} loading={['loading', 'settling', 'refreshing'].includes(data.resources.quality.status)} dup={dup} onClose={dismissal.close} onOpenComparison={pid=>onOpenResults?.('analysis',{analysisTab:'comparison',propertyId:pid})} onOpenSource={source => navigate({ type: 'source', source })} onOpenRecord={id => { const record = records.find(record => record.record_id === id); if (record) navigate({ type: 'record', record }) }} /> : detail.type === 'stage' ? <StageDetailPanel embedded stage={stage} initialAgentKey={detail.agentKey} onClose={dismissal.close} onShowStageInChat={onShowStageInChat} /> : source ? <>
        <header className="settings-header"><h2 data-detail-heading tabIndex={-1}>来源详情</h2><Button variant="ghost" size="sm" onClick={dismissal.close}>关闭</Button></header>
        <SourceDetails key={source.source_id+':'+data.deliveryRevision} scope={data} sources={sources} onOpenFigure={figure=>navigate({type:'figure',figure})} source={source} records={records} materials={data.resources.materials?.data||[]} onOpenSource={s=>navigate({type:'source',source:s})} onOpenRecord={record=>navigate({type:'record',record})}/>
      </> : null}
      {detail.type === 'record' && data.resources.sources.status === 'error' && <div className="resource-error">来源读取失败<Button size="sm" variant="outline" onClick={() => data.reload('sources')}>重试</Button></div>}
      {detail.type === 'record' && data.resources.quality.status === 'error' && <div className="resource-error">处理信息读取失败<Button size="sm" variant="outline" onClick={() => data.reload('quality')}>重试</Button></div>}
    </aside>
  </>
}
