import { useDismissTransition } from '@/hooks/useDismissTransition'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { useDialogFocus } from '@/hooks/useDialogFocus'

const CHAPTERS = [['quick', '快速上手'], ['samples', '浏览与回放样例'], ['query', '发起真实查询'], ['views', '理解三个主页面'], ['records', '阅读记录与来源'], ['export', '导出与常见状态']]
const asset = name => `${import.meta.env.BASE_URL}help/${name}.jpg`
function GuideImage({ name, alt, caption, onZoom }) {
  return <figure className="help-figure"><button onClick={() => onZoom({ name, alt })} aria-label={`放大：${alt}`}><img src={asset(name)} alt={alt} loading="lazy" /></button><figcaption>{caption}<span>点击图片查看大图</span></figcaption></figure>
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
    window.history.replaceState(null, '', `#help-${id}`)
  }
  return <div ref={pageRef} className="help-page" data-component="help-page"><header className="help-heading"><div><span className="eyebrow">AstroQuery AI 使用指南</span><h2>从科研问题，走到可追溯的数据</h2><p>选择一份已有成果开始阅读，或让智能体为你的问题查找、提取与整理数据。</p></div><Button variant="outline" onClick={onReturn}>返回原页面</Button></header>
    {pending && pending.type !== 'greeting' && <div className="notice"><span>{pending.title || '当前任务有待确认问题'}</span><Button variant="outline" size="sm" onClick={onPending}>去处理</Button></div>}
    <div className="help-layout"><nav aria-label="帮助章节">{CHAPTERS.map(([id, title], i) => <a key={id} href={`#help-${id}`} onClick={event => goToChapter(event, id)}><span>0{i + 1}</span>{title}</a>)}</nav><article className="help-reading">
      <section id="help-quick"><span className="help-step">01 / 从这里开始</span><h3>快速上手</h3><p>先看成果，再沿着来源和处理记录了解它是怎样得到的。首次使用可以先浏览演示样例，无需配置密钥。</p><svg className="help-flow" viewBox="0 0 760 108" role="img" aria-label="提出需求、查看执行、检查数据与来源、查看处理、导出结果五步使用路径">{['提出需求', '查看执行', '检查数据与来源', '查看处理', '导出结果'].map((text, i) => <g key={text}>{i < 4 && <path d={`M${i * 152 + 100},32 H${i * 152 + 188}`} stroke="var(--surface-border)" strokeWidth="2" />}<circle cx={i * 152 + 76} cy="32" r="22" fill="var(--accent-light)" /><text x={i * 152 + 76} y="37" textAnchor="middle" fill="var(--accent-text)" fontSize="15">{i + 1}</text><text x={i * 152 + 76} y="84" textAnchor="middle" fill="var(--content-fg)" fontSize="13">{text}</text></g>)}</svg><div className="help-actions"><Button variant="accent" onClick={onSamples}>查看演示样例</Button><Button variant="outline" onClick={onQuery}>进入新查询</Button></div></section>
      <section id="help-samples"><span className="help-step">02 / 先体验已有成果</span><h3>浏览与回放样例</h3><div className="help-two-column"><div><h4>查看成果</h4><p>直接打开已完成任务，查看全部记录、来源、研究图像和质量报告。原始样例保持只读。</p></div><div><h4>回放过程</h4><p>创建回放副本，按保存的事件重演步骤和确认过程。回放无需密钥，不消耗模型查询额度；速度可在设置中调整。</p></div></div><GuideImage name="entry" alt="样例画廊与可搜索的样例侧栏" caption="① 左栏搜索样例　② 查看数据成果　③ 回放已有过程。图中数量属于该样例。" onZoom={setZoom} /></section>
      <section id="help-query"><span className="help-step">03 / 查询你的研究问题</span><h3>发起真实查询</h3><ol className="help-steps"><li><strong>填写科研连接。</strong>在设置中填写模型 Key 与对应地域地址、ADS Token 和 Unpaywall 邮箱。可以先保存部分内容；四项连接齐全并重启后，才能发起新的实操查询。</li><li><strong>说明天体和所需性质。</strong>例如“查询昴星团 M45 的年龄、距离和金属丰度”。点击示例问题只会填入输入框，发送后才创建任务。</li><li><strong>核对初始确认。</strong>检查识别出的天体和研究性质，正确后点击确认。需要调整时选择修改，后台会等待你的回复。</li><li><strong>查看执行进展。</strong>可以切换视图、阅读历史或打开帮助，后台执行继续。向上阅读时暂停自动跟随，点击“查看最新进展”恢复。</li></ol><Button variant="outline" size="sm" onClick={onSettings}>打开科研连接设置</Button><p className="help-note">保存连接后重启生效。任务失败不会自动重跑；重试会创建新的实操任务。</p></section>
      <section id="help-views"><span className="help-step">04 / 找到你需要的信息</span><h3>理解三个主页面</h3><dl className="help-view-list"><div><dt>对话</dt><dd>提出问题、回复确认、阅读阶段产出及最后的成果概览。阶段卡可展开查看。</dd></div><div><dt>数据结果</dt><dd>完整记录、搜索筛选、来源与图像、评分、修改记录和数据洞察。任务完成后统一读取最终结果。</dd></div><div><dt>工作流</dt><dd>七个处理阶段、步骤、轮次、Agent 日志和全过程概览。查看历史阶段后可恢复跟随当前阶段。</dd></div></dl><p>成果中的性质分布可以直接打开对应记录筛选。待确认问题可从不同视图定位回对话中的确认卡。</p></section>
      <section id="help-records"><span className="help-step">05 / 读懂数值及其来历</span><h3>阅读记录与来源</h3><p>点击记录行打开详情。先读天体、性质、测量值与单位，再检查出处及原文位置；有处理记录时，可以逐步查看每次变化和已有原因。</p><GuideImage name="record" alt="数据结果列表与完整记录信息" caption="图中展示数据结果列表、实体性质、测量数值与提取方式；点击记录行可继续查看详细出处与证据。" onZoom={setZoom} /><div className="help-two-column"><div><h4>论文与数据库</h4><p>论文可查看页码、原文摘录和已有定位图；数据库可查看表、列及天体主键，以及来源的观测设施和研究方法。</p></div><div><h4>研究图像与洞察</h4><p>研究图像是相关研究图片，未必是某条测量的取值依据。洞察中分别展开字段解释、测量分布或字段关系，引用均来自已有报告。</p></div></div></section>
      <section id="help-export"><span className="help-step">06 / 把结果带到后续研究</span><h3>导出与常见状态</h3><div className="help-two-column"><div><h4>当前筛选数据</h4><p>从数据结果进入导出，核对筛选范围，并独立选择或排除记录。格式配置在同一弹层内完成。</p></div><div><h4>任务文件与数据包</h4><p>下载任务实际生成的文件，保留交付时的数据和报告。它与当前筛选导出的范围可能不同。</p></div></div><GuideImage name="export" alt="统一导出入口及筛选数据与任务文件两个范围" caption="① 确认导出范围　② 核对记录或文件　③ 选择格式并下载。" onZoom={setZoom} /><dl className="help-status-list"><div><dt>等待确认</dt><dd>任务等待你的选择，点击待办入口回复后继续。</dd></div><div><dt>结果整理中</dt><dd>任务或阶段已有进展，最终资源尚未齐全；晚到内容会更新原区域。</dd></div><div><dt>连接中断</dt><dd>查看连接状态并重新连接；界面会恢复已有事件，不另建任务。</dd></div><div><dt>失败或取消</dt><dd>保留已有执行内容及实际可用的部分结果，不显示成成功。取消不会删除历史任务。</dd></div></dl></section>
    </article></div>{zoom && <Zoom image={zoom} onClose={() => setZoom(null)} />}</div>
}
