import SummaryBasisDetail from '@/components/results/SummaryBasisDetail'
import BackToTop from '@/components/ui/BackToTop'
import KnowledgeDetail from '@/components/results/KnowledgeDetail'
import ResearchFigure from '@/components/results/ResearchFigure'
import { getRecord, getSource, getFigure } from '@/services/api'
import { useRecordsPage } from '@/hooks/useRecordsPage'
import { scopedRecordReference, scopedDrawerResources } from '@/lib/resultDetails'
import { useLayoutEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import SourceDetails from '@/components/results/SourceDetails'
import RecordDetail from '@/components/results/RecordDetail'
import { Excerpt } from '@/components/results/ReadableContent'
import StageDetailPanel from '@/components/workflow/StageDetailPanel'
import { buildDupIndex } from '@/lib/dupMarkers'
import { sourceName, readableText, SOURCE_TYPES } from '@/lib/readableData'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import { useDismissTransition } from '@/hooks/useDismissTransition'
import { useContentTransition } from '@/hooks/useContentTransition'
import AnswerReference from '@/components/chat/AnswerReference'

export default function ContextDrawer({ detail, data, pipeline, onClose, onChange, onShowStageInChat, onOpenResults, selection }) {
  const [width, setWidth] = useState(580)
  const [history, setHistory] = useState([])
  const navigation = useRef(null)
  const wasLoadingReference = useRef(false)
  const currentDetail=useRef(detail);currentDetail.current=detail
  const [loadError,setLoadError]=useState('')
  const relatedScope={taskId:detail?.taskId||data.taskId,deliveryId:detail?.answerScope?.delivery_id||data.deliveryId,revision:detail?.answerScope?.delivery_revision||data.deliveryRevision,atSeq:detail?.answerScope?detail.answerScope.at_seq:data.atSeq,sealedOnly:detail?.answerScope?detail.answerScope.sealed_only:data.sealedOnly}
  const readOptions={atSeq:relatedScope.atSeq,sealedOnly:relatedScope.sealedOnly}
  const relatedKey=JSON.stringify([relatedScope,detail?.source?.source_id])
  const [relatedPaging,setRelatedPaging]=useState(null)
  const relatedOffset=relatedPaging?.key===relatedKey?relatedPaging.offset:0
  const related=useRecordsPage(relatedScope,{source_id:detail?.source?.source_id,quick:'all',offset:relatedOffset,limit:50,collapse_duplicates:false},detail?.type==='source'&&detail.source?.protocol_version===2&&!!detail.source?.source_id)
  const direction = useRef(1)
  const dismissal = useDismissTransition(onClose, { duration: 160, active: !!detail, identity: detail })
  const ref = useDialogFocus(!!detail, dismissal.close, { trap: true })
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
    if (wasLoadingReference.current && !ref.current.contains(document.activeElement) && document.activeElement === document.body) {
      const heading = ref.current.querySelector('[data-detail-heading]') || ref.current
      heading.focus({ preventScroll: true })
    }
    wasLoadingReference.current = detail.type === 'agent-ref-loading'
    if (restoring) {
      const origin = [...ref.current.querySelectorAll('[data-detail-action]')].find(element => element.getAttribute('data-detail-action') === restoring.focusKey)
      ;(origin || ref.current.querySelector('[data-detail-heading]') || ref.current)?.focus({ preventScroll: true })
    }
  }, [detail])
  useContentTransition(ref, detail ? `${detail.type}:${detail.record?.record_id || detail.source?.source_id || detail.stageId}:${detail.agentKey || ''}` : '', { active: Boolean(detail), selector: '.record-detail-body, .context-content', axis: 'x', distance: 16 * direction.current, duration: 240 })
  if (!detail) return null
  const loadRecord = async recordId => {
    const scope = detail.answerScope
    if (!scope) return
    const previous = detail
    try {
      const record = await getRecord(detail.taskId || data.taskId, scope.delivery_id, scope.delivery_revision, recordId, readOptions)
      if (currentDetail.current === previous && record) await navigate({ type: 'record', record })
    } catch (error) {
      if (currentDetail.current === previous) setLoadError(error.message)
    }
  }
  const navigate = async next => {
    const previousDetail=detail
    if(next.type==='record'&&next.record.details_loaded===false){try{const r=next.record;const targetTaskId=r.task_id||r.source?.task_id||data?.taskId||pipeline?.taskId;next={...next,record:await getRecord(targetTaskId,r.delivery_id,r.delivery_revision,r.record_id,readOptions)}}catch(e){setLoadError(e.message);return}if(currentDetail.current!==previousDetail)return}
    if(['source','figure','record'].includes(next.type) && relatedScope.deliveryId && next[next.type]?.legacy_version!==1) {
      try {
        const item=next[next.type], itemId=item[`${next.type}_id`]
        if(next.type!=='record'&&itemId) {
          const full=await (next.type==='source'?getSource:getFigure)(relatedScope.taskId,relatedScope.deliveryId,relatedScope.revision,itemId,readOptions)
          if(full) next={...next,[next.type]:{...item,...full}}
        }
        const sourceId=next.record?.source_id||next.figure?.source_id
        if(sourceId)next={...next,linkedSource:await getSource(relatedScope.taskId,relatedScope.deliveryId,relatedScope.revision,sourceId,readOptions)}
      }catch(error){setLoadError(error.message);return}
      if(currentDetail.current!==previousDetail)return
    }
    if (detail.agentContext || detail.answerScope) {
      next = { ...next, taskId:relatedScope.taskId, agentContext: true, answerScope: detail.answerScope }
    }
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
  const cachedResources=scopedDrawerResources(data,relatedScope)
  const quality = cachedResources.quality?.data
  const records = detail.type==='source'&&detail.source?.protocol_version===2 ? related.data?.items || [] : cachedResources.records?.data || []
  const loadedSources = cachedResources.sources?.data || []
  const sources = detail.linkedSource && !loadedSources.some(item => item.source_id === detail.linkedSource.source_id) ?
    [detail.linkedSource, ...loadedSources] : loadedSources
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
  const gallery=(cachedResources.figures?.data||[]).filter(f=>!detail.figure?.galleryIds||detail.figure.galleryIds.includes(f.figure_id))
  const figureIndex=gallery.findIndex(f=>f.figure_id===detail.figure?.figure_id)
  const moveFigure=step=>navigate({type:'figure',figure:{...gallery[(figureIndex+step+gallery.length)%gallery.length],galleryIds:detail.figure?.galleryIds}})
  const source = detail.source
  const authors = Array.isArray(source?.authors) ? source.authors.map(readableText).filter(Boolean) : []
  return <>
    <div className={`context-backdrop${detail.type==='knowledge'?' knowledge-blur-backdrop':''}`} data-closing={dismissal.closing || undefined} onClick={dismissal.close} />
    <aside ref={ref} data-closing={dismissal.closing || undefined} onAnimationEnd={dismissal.onAnimationEnd} onKeyDownCapture={dismissal.onKeyDownCapture} role="dialog" aria-modal="true" aria-label="上下文详情" tabIndex={-1} className="context-drawer animate-drawer-in overlay" style={{ width:detail.type==='knowledge'?Math.max(640,width):width }}>
      <div className="drawer-resize" onPointerDown={startResize} />
      {loadError&&<p className="resource-error">{loadError}</p>}
      {history.length > 0 && !source && detail.type !== 'figure' && <div className="drawer-back-row"><Button variant="ghost" size="sm" onClick={goBack}>← 返回上一项</Button></div>}
      {['agent-reference', 'agent-ref-loading'].includes(detail.type) ? <AnswerReference detail={detail} navigate={navigate} onRecord={loadRecord} onClose={dismissal.close} /> :
      detail.type === 'loading-record' ? <><header className="record-detail-heading"><strong>{detail.record.field_name}</strong><Button variant="ghost" onClick={dismissal.close}>关闭</Button></header>
        <section className="context-content" aria-busy="true"><p className="record-measurement">{detail.record.field_value} {detail.record.field_unit}</p><p role="status">正在读取原件与处理记录…</p></section></> : detail.type === 'figure' ? <>
        <header className="context-drawer-header">
          <div className="drawer-header-left">
            {history.length > 0 && (
              <button
                type="button"
                className="drawer-back-pill active-press"
                onClick={goBack}
                title="返回上一级"
              >
                <Icon.ArrowLeft style={{ width: 14, height: 14 }} />
                <span>返回</span>
              </button>
            )}
            <h2 data-detail-heading tabIndex={-1} className="drawer-header-title">
              <Icon.Image className="drawer-title-icon" style={{ width: 16, height: 16, color: 'var(--accent)' }} />
              <span>研究图像详情</span>
            </h2>
          </div>
          <div className="workbench-drawer-actions">
            {selection&&detail.figure.figure_id&&<Button variant="outline" size="sm" aria-pressed={selection.has('figures',detail.figure.figure_id)} onClick={()=>selection.toggle('figures',[detail.figure])}>{selection.has('figures',detail.figure.figure_id)?'取消选择':'选择图像'}</Button>}
          <button
            type="button"
            className="drawer-close-circle active-press"
            onClick={dismissal.close}
            aria-label="关闭"
          >
            <Icon.Close style={{ width: 14, height: 14 }} />
          </button>
          </div>
        </header>
        <ResearchFigure onPrevious={gallery.length>1?()=>moveFigure(-1):undefined} onNext={gallery.length>1?()=>moveFigure(1):undefined} figure={detail.figure} sources={detail.linkedSource ? [detail.linkedSource] : sources} onOpenSource={source=>selection&&source?.source_id?onOpenResults?.('candidates',{materialId:source.source_id}):navigate({type:'source',source})}/>
      </> : detail.type === 'summary-basis' ? <SummaryBasisDetail detail={detail} onClose={dismissal.close} onKnowledge={block=>navigate({type:'knowledge',block})} onRecord={loadRecord} onSource={source_id=>navigate({type:'source',source:{source_id}})}/> : detail.type === 'knowledge' ? <KnowledgeDetail key={`${detail.block?.entry_id}:${detail.block?.archived}`} block={detail.block} referenceScope={relatedScope} onOpenCurrent={block=>navigate({type:'knowledge',block})} onClose={dismissal.close}/> : detail.type === 'record' ? <RecordDetail key={detail.record.record_id} embedded selection={selection} record={detail.record} quality={quality} sources={sources} loading={['loading', 'settling', 'refreshing'].includes(cachedResources.quality?.status)} dup={dup} onClose={dismissal.close} onOpenComparison={pid=>onOpenResults?.('analysis',{analysisTab:'comparison',propertyId:pid})} onOpenSource={source=>selection&&source?.source_id?onOpenResults?.('candidates',{materialId:source.source_id,propertyId:detail.record.property_id}):navigate({type:'source',source})} onOpenRecord={id => navigate({ type: 'record', record: scopedRecordReference(records,id,relatedScope) })} /> : detail.type === 'stage' ? <StageDetailPanel embedded stage={stage} initialAgentKey={detail.agentKey} onClose={dismissal.close} onShowStageInChat={onShowStageInChat} /> : source ? <>
        <header className="context-drawer-header">
          <div className="drawer-header-left">
            {history.length > 0 && (
              <button
                type="button"
                className="drawer-back-pill active-press"
                onClick={goBack}
                title="返回上一级"
              >
                <Icon.ArrowLeft style={{ width: 14, height: 14 }} />
                <span>返回记录</span>
              </button>
            )}
            <h2 data-detail-heading tabIndex={-1} className="drawer-header-title">
              {source.kind === 'cited' ? (
                <>
                  <Icon.Quote style={{ width: 16, height: 16, color: 'var(--accent)' }} />
                  <span>原文引用详情</span>
                </>
              ) : (
                <>
                  <Icon.BookOpen style={{ width: 16, height: 16, color: 'var(--accent)' }} />
                  <span>来源文献档案</span>
                </>
              )}
            </h2>
          </div>
          <button
            type="button"
            className="drawer-close-circle active-press"
            onClick={dismissal.close}
            title="关闭详情"
            aria-label="关闭详情"
          >
            <Icon.Close style={{ width: 14, height: 14 }} />
          </button>
        </header>
        {source.protocol_version===2&&source.source_id&&<div className="records-pagination"><span role="status">{related.status==='error'?related.error:related.status!=='success'?'正在读取关联记录…':`关联记录 ${related.data.total} 条 · 第 ${relatedOffset/50+1} 页`}</span>{related.status==='error'&&<button onClick={related.reload}>重试</button>}<button disabled={!relatedOffset} onClick={()=>setRelatedPaging({key:relatedKey,offset:relatedOffset-50})}>上一页</button><button disabled={related.status!=='success'||relatedOffset+50>=related.data.total} onClick={()=>setRelatedPaging({key:relatedKey,offset:relatedOffset+50})}>下一页</button></div>}
        <SourceDetails key={source.source_id+':'+relatedScope.revision} scope={{...data,taskId:relatedScope.taskId,deliveryId:relatedScope.deliveryId,deliveryRevision:relatedScope.revision,atSeq:relatedScope.atSeq,sealedOnly:relatedScope.sealedOnly}} sources={sources} onOpenFigure={figure=>navigate({type:'figure',figure})} source={source} records={records} recordsTotal={related.data?.total} recordsStatus={source.protocol_version===2&&source.source_id?related.status:'success'} materials={cachedResources.materials?.data||[]} onOpenSource={s=>navigate({type:'source',source:s})} onOpenRecord={record=>navigate({type:'record',record})}/>
      </> : null}
      {detail.type === 'record' && cachedResources.sources?.status === 'error' && <div className="resource-error">来源读取失败<Button size="sm" variant="outline" onClick={() => data.reload('sources')}>重试</Button></div>}
      {detail.type === 'record' && cachedResources.quality?.status === 'error' && <div className="resource-error">处理信息读取失败<Button size="sm" variant="outline" onClick={() => data.reload('quality')}>重试</Button></div>}
      <BackToTop key={`${detail.type}:${detail.record?.record_id||detail.source?.source_id||''}`} scroller=".record-detail-body, .context-content" floating />
    </aside>
  </>
}
