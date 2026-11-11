import { Component, Suspense, lazy, memo, useCallback, useId, useMemo, useState } from 'react'
import { Icon } from '@/components/icons'
import Markdown from '@/lib/markdown'
import { LatexMath, LatexText, renderMath } from '@/components/results/LatexMath'
import { artifactUrl } from '@/services/api'
import { readState, stateKey } from './followupState'
import { AnswerTable, BlockHeader, CiteButton, recordText, useCopy } from './AnswerData'

const AnswerPlot = lazy(() => import('./AnswerPlot'))
const ExploreBlock = lazy(() => import('./ExploreBlock'))
const AnswerRelation = lazy(() => import('./AnswerRelation'))

const markerPattern = /\[(?:REC|SOURCE|FIG|PROP|KB|THEORY|ARB|COMP|CMP|DIFF|DEF|KNOW|CONFLICT):[^\]\n]+\]/g
export const AnswerMarkdown = memo(function AnswerMarkdown({ text, citations, onCite }) {
  const refs = useMemo(() => new Map(Object.values(citations).map(citation => [citation.marker, citation])), [citations])
  const markdown = useMemo(() => String(text || '').replace(/\[(?:REC|SOURCE|FIG|DEF|THEORY|ARB):[^\]\n]*$/, '').replace(markerPattern, raw => {
    const citation = refs.get(raw.slice(1, -1)) || refs.get(raw)
    return citation ? '[来源](#aq-ref-' + citation.citation_id + ')' : raw
  }), [text, refs])
  const links = useMemo(() => ({
    a: ({ href, children }) => {
      if (href?.startsWith('#aq-ref-')) {
        const citation = citations[href.slice(8)]
        if (citation) return <CiteButton id={citation.citation_id} onCite={onCite}>{citation.label}</CiteButton>
      }
      return href ? <a href={href} target="_blank" rel="noreferrer">{children}</a> : children
    },
    img: () => null,
  }), [citations, onCite])
  return <Markdown className="research-prose" components={links} style={{}}>{markdown}</Markdown>
})

function Formula({ block, onAsk, onRepair }) {
  const [status, copy] = useCopy()
  const valid = useMemo(() => Boolean(renderMath(block.latex, true)), [block.latex])
  return <div className="research-component research-formula">
    <BlockHeader title={block.title || '公式'}>
      {valid && <button type="button" className="research-action" onClick={() => copy(block.latex)}><Icon.Copy width={15} height={15} />{status || '复制公式'}</button>}
    </BlockHeader>
    <LatexMath math={block.latex} displayMode />
    {!valid && <button type="button" className="research-action" onClick={onRepair}><Icon.Refresh width={14} height={14} />重试公式</button>}
    {!!block.variables?.length && <dl className="research-variables">
      {block.variables.map((item, i) => <div key={i}>
        <dt><LatexMath math={item.symbol} /></dt><dd><LatexText text={item.description} />
          {(item.value || item.unit) && <span className="research-quiet"> · {[item.value, item.unit].filter(Boolean).join(' ')}</span>}
        </dd>
      </div>)}
    </dl>}
    {valid && <footer className="research-block-foot"><button type="button" className="research-action"
      onClick={() => onAsk({ prompt: '请解释这个公式：' + block.latex, refs: block.refs })}>解释这个公式</button></footer>}
  </div>
}

function Comparison({ block, citations, onCite }) {
  return <div className="research-component">
    <BlockHeader title={block.title || '并列比较'} />
    <div className="research-compare">{block.items.map((item, i) => <section key={i}>
      <h4>{item.title || '比较项 ' + (i + 1)}</h4>
      <AnswerMarkdown text={item.markdown} citations={citations} onCite={onCite} />
      {!!item.rows?.length && <ul>{item.rows.map(row => <li key={row.id}>
        <CiteButton id={row.citation_id} onCite={onCite}>{recordText(row)}</CiteButton><span> · {row.source}</span>
      </li>)}</ul>}
      {!!item.refs?.length && <References ids={item.refs} onCite={onCite} citations={citations} />}
    </section>)}</div>
  </div>
}

function GalleryItem({ figure, taskId, onCite, onAsk, marker }) {
  const [status, setStatus] = useState('loading')
  const source = Array.isArray(figure.source) ? figure.source[0] : figure.source
  return <figure>
    <button className="research-gallery-image" type="button" onClick={() => onCite(figure.citation_id)} aria-label={'打开' + figure.label}>
      {figure.image_artifact_id && status !== 'failed' ? <>
        {status === 'loading' && <span className="research-image-loading">正在读取图像…</span>}
        <img loading="lazy" decoding="async" alt={figure.label}
          src={artifactUrl(taskId, figure.image_artifact_id)} onLoad={() => setStatus('ready')} onError={() => setStatus('failed')} />
      </> :
        <span>查看图像与原页</span>}
    </button>
    <figcaption><strong>{figure.label}</strong>
      {source && <span className="research-image-source" title={source}>{source}</span>}
      {figure.caption && <p className="research-caption"><LatexText text={figure.caption} /></p>}
      <div className="research-controls">
        <CiteButton id={figure.citation_id} onCite={onCite}>查看图注和原页</CiteButton>
        <button className="research-action" type="button" onClick={() => onAsk({ markers: marker ? [marker] : [], prompt: '这幅图展示了什么？' })}>就此追问</button>
      </div>
    </figcaption>
  </figure>
}

function References({ ids, citations, onCite }) {
  const available = ids.filter(id => citations[id])
  if (!available.length) return null
  return <div className="research-block-refs" aria-label="参考依据">
    {available.map(id => <CiteButton key={id} id={id} onCite={onCite}>{citations[id].label}</CiteButton>)}
  </div>
}

class BlockBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidUpdate(previous) {
    if (this.state.failed && previous.block !== this.props.block) this.setState({ failed: false })
  }
  render() {
    return this.state.failed ? <div className="research-local-error" role="status">
      <span>这个组件暂时无法显示</span>
      <button className="research-action" type="button" onClick={this.props.onRepair}>重试此组件</button>
    </div> : this.props.children
  }
}

function BlockContent(props) {
  const { block, citations, onCite, onAsk, onRepair, taskId } = props
  switch (block.type) {
    case 'text': return <>
      {block.title && <h3 className="research-text-heading">{block.title}</h3>}
      <AnswerMarkdown text={block.markdown} citations={citations} onCite={onCite} />
    </>
    case 'formula': return <Formula {...props} />
    case 'table': return <AnswerTable {...props} />
    case 'chart': return <AnswerPlot {...props} />
    case 'compare': return <Comparison {...props} />
    case 'relation': return <AnswerRelation {...props} />
    case 'explore': return <ExploreBlock {...props} />
    case 'gallery': return <div className="research-component">
      <BlockHeader title={block.title || '研究图像'} />
      <div className="research-gallery">{block.items.map(figure => <GalleryItem key={figure.id} figure={figure} taskId={taskId}
        onCite={onCite} onAsk={onAsk} marker={citations[figure.citation_id]?.marker} />)}</div>
    </div>
    default: return <div className="research-local-error" role="status">
      <span>{block.title || '这个回答组件'}暂未生成</span>
      <button className="research-action" type="button" onClick={onRepair}><Icon.Refresh width={15} height={15} />重试此组件</button>
    </div>
  }
}

const AnswerBlock = memo(function AnswerBlock({ block, messageId, citations, onAsk, onRetry, ...props }) {
  const id = useId()
  const key = stateKey(messageId, block.id)
  const [state, setState] = useState(() => readState(key))
  const change = useCallback(next => setState(previous => {
    const updated = { ...previous, ...next }
    if ('recordIds' in next || 'values' in next) updated.touchedAt = Date.now()
    try { localStorage.setItem(key, JSON.stringify(updated)) } catch { /* session still works */ }
    return updated
  }), [key])
  const ask = useCallback(selection => onAsk({
    ...selection,
    markers: [...new Set([...(selection.markers || []), ...(selection.refs || []).map(id => citations[id]?.marker).filter(Boolean)])],
    selections: selection.values ? [{ message_id: messageId, block_id: block.id, values: selection.values }] : [],
  }), [onAsk, citations, messageId, block.id])
  const repair = () => onRetry(messageId, block.id)
  return <div className="research-answer-block" data-block-type={block.type} data-block-id={block.id}>
    <BlockBoundary block={block} onRepair={repair}>
      <Suspense fallback={<p className="research-quiet">正在加载组件…</p>}>
        <BlockContent {...props} block={block} state={state} change={change} citations={citations}
          onAsk={ask} onRepair={repair} instanceId={id} />
      </Suspense>
    </BlockBoundary>
    {!!block.refs?.length && <References ids={block.refs} citations={citations} onCite={props.onCite} />}
  </div>
})

export default memo(function AnswerBlocks({ message, taskId, dark, onCite, onAsk, onRetry }) {
  const citations = useMemo(() => Object.fromEntries((message.citations || []).map(c => [c.citation_id, c])), [message.citations])
  const open = useCallback(citationId => onCite(message, citationId), [onCite, message])
  if (!message.answer?.blocks) return <AnswerMarkdown text={message.content} citations={citations} onCite={open} />
  return <div className="research-answer">{message.answer.blocks.map(block =>
    <AnswerBlock key={message.id + ':' + block.id} block={block} messageId={message.id} taskId={taskId}
      citations={citations} dark={dark} onCite={open} onAsk={onAsk} onRetry={onRetry} />,
  )}</div>
})
