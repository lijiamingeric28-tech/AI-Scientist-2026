import { useDismissTransition } from '@/hooks/useDismissTransition'
import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import BackToTop from '@/components/ui/BackToTop'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import { HELP_SECTIONS } from './guide'

const CHAPTERS = HELP_SECTIONS.map(({ id, title }) => [id, title])
const asset = name => `${import.meta.env.BASE_URL}help-v2/${name}.png`
function GuideImage({ name, alt, caption, onZoom }) {
  return <figure className="help-figure"><button onClick={() => onZoom({ name, alt })} aria-label={`放大：${alt}`}><img src={asset(name)} alt={alt} loading="lazy" width="1920" height="1080" /></button><figcaption>{caption} 点击图片可放大阅读。</figcaption></figure>
}
function Zoom({ image, onClose }) {
  const dismissal = useDismissTransition(onClose)
  const ref = useDialogFocus(true, dismissal.close)
  return <div className="help-image-backdrop" data-closing={dismissal.closing || undefined} onClick={dismissal.close}><section ref={ref} data-closing={dismissal.closing || undefined} onAnimationEnd={dismissal.onAnimationEnd} onKeyDownCapture={dismissal.onKeyDownCapture} role="dialog" aria-modal="true" aria-label={image.alt} tabIndex={-1} onClick={e => e.stopPropagation()}><header><span>{image.alt}</span><div className="help-actions"><a href={asset(image.name)} target="_blank" rel="noreferrer">查看原尺寸图片</a><Button variant="outline" size="sm" onClick={dismissal.close}>关闭</Button></div></header><img src={asset(image.name)} alt={image.alt} /></section></div>
}
export default function HelpPage({ onReturn, onSamples, onQuery, onSettings, pending, onPending }) {
  const [zoom, setZoom] = useState(null)
  const pageRef = useRef(null)
  const goToChapter = (event, id) => {
    event.preventDefault()
    const page = pageRef.current, target = page?.querySelector(`#help-${id}`)
    if (!target) return
    page.scrollTo({ top: page.scrollTop + target.getBoundingClientRect().top - page.getBoundingClientRect().top - 24, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
  }
  return <div ref={pageRef} className="help-page" data-component="help-page"><header className="help-heading"><div><h2>AstroQuery AI 使用帮助</h2><p>从确认研究需求，到核对原件、筛选测量和导出。按目录找到当前操作；截图来自真实查询，数量与状态以你打开的任务为准。</p></div><Button variant="outline" onClick={onReturn}>返回原页面</Button></header>
    {pending && pending.type !== 'greeting' && <div className="notice"><span>{pending.title || '当前任务有待确认问题'}</span><Button variant="outline" size="sm" onClick={onPending}>去处理</Button></div>}
    <div className="help-layout"><nav aria-label="帮助章节">{CHAPTERS.map(([id, title], i) => <a key={id} href={`#help-${id}`} onClick={event => goToChapter(event, id)}><span>{String(i + 1).padStart(2, '0')}</span>{title}</a>)}</nav><article className="help-reading">
      {HELP_SECTIONS.map(section => <section key={section.id} id={`help-${section.id}`}>
        <h3>{section.title}</h3>
        {section.paragraphs?.map(text => <p key={text}>{text}</p>)}
        {section.id === 'quick' && <div className="help-actions"><Button onClick={onQuery}>新建科研查询</Button><Button variant="outline" onClick={onSamples}>查看演示样例</Button><Button variant="outline" onClick={onSettings}>打开设置</Button></div>}
        {section.steps && <ol className="help-steps">{section.steps.map(text => <li key={text}>{text}</li>)}</ol>}
        {section.definitions && <dl className="help-status-list">{section.definitions.map(([term, text]) => <div key={term}><dt>{term}</dt><dd>{text}</dd></div>)}</dl>}
        {section.image && <GuideImage name={section.image[0]} alt={section.image[1]} caption={section.image[2]} onZoom={setZoom} />}
        {section.subsections?.map(part => <div className="help-subsection" key={part.title}><h4>{part.title}</h4><p>{part.text}</p>{part.image && <GuideImage name={part.image[0]} alt={part.image[1]} caption={part.image[2]} onZoom={setZoom} />}</div>)}
        {section.after?.map(text => <p key={text}>{text}</p>)}
        {section.moreImages?.map(([name, alt, caption]) => <GuideImage key={name} name={name} alt={alt} caption={caption} onZoom={setZoom} />)}
        {section.details && <details><summary>{section.details[0]}</summary><p>{section.details[1]}</p></details>}
      </section>)}
    </article></div><BackToTop />{zoom && <Zoom image={zoom} onClose={() => setZoom(null)} />}</div>
}
