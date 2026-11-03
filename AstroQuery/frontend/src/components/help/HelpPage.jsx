import { useDismissTransition } from '@/hooks/useDismissTransition'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { useDialogFocus } from '@/hooks/useDialogFocus'

const CHAPTERS = [['quick', '快速上手'], ['samples', '查询目录与只读回放'], ['query', '发起真实查询'], ['views', '理解三个主页面'], ['records', '阅读记录与来源'], ['export', '导出与常见状态']]
const asset = name => `${import.meta.env.BASE_URL}help-v1/${name}.png`
function GuideImage({ name, alt, caption, onZoom }) {
  return <figure className="help-figure"><button onClick={() => onZoom({ name, alt })} aria-label={`放大：${alt}`}><img src={asset(name)} alt={alt} loading="lazy" /></button><figcaption>{caption}</figcaption></figure>
}
function Zoom({ image, onClose }) {
  const dismissal = useDismissTransition(onClose)
  const ref = useDialogFocus(true, dismissal.close)
  return <div className="help-image-backdrop" data-closing={dismissal.closing || undefined} onClick={dismissal.close}><section ref={ref} data-closing={dismissal.closing || undefined} onAnimationEnd={dismissal.onAnimationEnd} onKeyDownCapture={dismissal.onKeyDownCapture} role="dialog" aria-modal="true" aria-label={image.alt} tabIndex={-1} onClick={e => e.stopPropagation()}><header><span>{image.alt}</span><Button variant="outline" size="sm" onClick={dismissal.close}>关闭</Button></header><img src={asset(image.name)} alt={image.alt} /></section></div>
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
  return <div ref={pageRef} className="help-page" data-component="help-page"><header className="help-heading"><div><h2>开始使用 AstroQuery</h2></div><Button variant="outline" onClick={onReturn}>返回原页面</Button></header>
    {pending && pending.type !== 'greeting' && <div className="notice"><span>{pending.title || '当前任务有待确认问题'}</span><Button variant="outline" size="sm" onClick={onPending}>去处理</Button></div>}
    <div className="help-layout"><nav aria-label="帮助章节">{CHAPTERS.map(([id, title], i) => <a key={id} href={`#help-${id}`} onClick={event => goToChapter(event, id)}><span>0{i + 1}</span>{title}</a>)}</nav><article className="help-reading">
      <section id="help-quick"><h3>从一个问题开始</h3><p>点击“新建查询”，输入天体和想了解的性质，再点“开始查询”。点示例可以先把问题放进输入框，修改后再发出。</p><div className="stage-links"><Button onClick={onQuery}>新建查询</Button><Button variant="outline" onClick={onSettings}>打开设置</Button></div><GuideImage name="home" alt="科研查询输入框和示例" caption="一个问题可以包含多项性质。" onZoom={setZoom}/></section>
      <section id="help-samples"><h3>打开历史与回放</h3><p>在左栏按天体、性质和时间辨认查询。点击名称看已保存的结果，点击播放图标回看当时的过程。“演示样例”有独立的目录。</p><p>播放器可以暂停、变速、拖动时间轴或跳到阶段。审核出现时会显示当时的问题与锁定的原答，点击“提交并继续回放”后查看原回答的应用与复检。查看最终结果可以直接离开回放。</p><Button variant="outline" onClick={onSamples}>查看演示目录</Button></section>
      <section id="help-query"><h3>确认请求与回答审核</h3><ol className="help-steps"><li>在设置中配置模型和文献连接。在“检索与显示”选择 ADS 排序。</li><li>核对天体，从候选性质中选择 1–5 项。性质旁的信息按钮可以查看定义。存在缺口时，确认是否继续查询有效项。</li><li>检索开始前可以继续编辑，也可以暂时退出。确认并开始后，本次请求固定。</li><li>需要审核时，先读问题和原件，再选择判断并填写依据。证据仍不足时可以选“证据不足，暂不判断”。已保存的回答和复检结果可以在质量检查卡中回看。</li></ol></section>
      <section id="help-views"><h3>看进度与结果</h3><p>“对话”按时间显示八个阶段。点开进行中的卡片可以看当前步骤；文献下载按每项性质显示已取得的篇数。任务完成后，标题区的“查看数据结果”直接打开记录表。</p><p>“执行明细”可以查看各阶段进入的时间、耗时和局部异常。点击“在对话查看”可回到对应阶段。</p><GuideImage name="workflow" alt="各阶段用时与进入次数" caption="耗时概览使用这次任务保存的时间。" onZoom={setZoom}/></section>
      <section id="help-records"><h3>从测量追到原文</h3><p>在“数据结果 → 记录”按性质或来源筛选，再打开一行。详情依次展示性质、主值与单位、不确定度、主值处理、原文定位和参考资料。误差分量各自保留，展开可看分量、原单位和原式。</p><GuideImage name="record" alt="SN 2014J 的 9.80 mag 测量及 PDF 第 13 页" caption="点击“打开原PDF第13页”查看完整原件，点击缩略图放大保存的原页。" onZoom={setZoom}/><p>星表记录可核对表名、原行和单元格，官方附表还能追到所属论文。“资料与图像”汇集取得的资料、引用和研究图像。“质量与洞察”可查看任务分项、处理变更和每项性质的解释。</p></section>
      <section id="help-export"><h3>导出当前范围的记录</h3><p>点击“导出结果”，核对交付版本和勾选数量，再选格式。可用格式包括测量明细 CSV、研究数据包 ZIP、分组宽表 CSV、按性质 JSON 和完整 JSON。旧版归档显示它支持的格式。</p><GuideImage name="export" alt="选择导出记录和格式" caption="勾选只影响本次文件；此前生成的文件在“已生成文件”中。" onZoom={setZoom}/><p>导出使用已保存的交付版本。需要更换范围时回到记录表修改筛选，再重新打开导出。</p></section>
    </article></div>{zoom && <Zoom image={zoom} onClose={() => setZoom(null)} />}</div>
}
