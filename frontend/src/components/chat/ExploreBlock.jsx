import { useEffect, useMemo, useRef, useState } from 'react'
import { LatexMath, LatexText } from '@/components/results/LatexMath'
import { BlockHeader } from './AnswerData'
import { ChartCanvas } from './AnswerPlot'
import { useAnswerChartTheme } from '@/hooks/useAnswerChartTheme'

const precision = value => Number(value.toPrecision(7)).toString()

function ParameterInput({ parameter: p, value, onChange }) {
  const [typed, setTyped] = useState(String(value))
  useEffect(() => setTyped(String(value)), [value])
  function commit() {
    const number = Number(typed)
    if (typed.trim() && Number.isFinite(number)) onChange(Math.min(p.max, Math.max(p.min, number)))
    else setTyped(String(value))
  }
  return <div className="research-parameter">
    <label htmlFor={'explore-' + p.domId}><LatexText text={p.label} />{p.unit && <span className="research-quiet"> · {p.unit}</span>}</label>
    {p.choices.length ? <select id={'explore-' + p.domId} value={value} onChange={e => onChange(Number(e.target.value))}>
      {[...new Set([...p.choices, p.value])].sort((a, b) => a - b).map(choice => <option key={choice} value={choice}>{choice}</option>)}
    </select> :
      <div className="research-parameter-inputs">
        <input id={'explore-' + p.domId} type="number" step="any" min={p.min} max={p.max} value={typed}
          onChange={e => setTyped(e.target.value)} onBlur={commit} onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }} />
        <input type="range" aria-label={p.label + ' 滑杆'} min={p.min} max={p.max} step={p.step} value={value}
          onChange={e => onChange(Number(e.target.value))} />
      </div>}
  </div>
}

export default function ExploreBlock({ block, state, change, onAsk, onRepair, dark, instanceId }) {
  const colors=useAnswerChartTheme()
  const worker = useRef(null)
  const latest = useRef(0)
  const [result, setResult] = useState(null)
  const values = useMemo(() => Object.fromEntries(block.parameters.map(p => [p.name, state.values?.[p.name] ?? p.value])), [block.parameters, state.values])
  useEffect(() => {
    const thread = new Worker(new URL('./explore.worker.js', import.meta.url), { type: 'module' })
    worker.current = thread
    thread.onmessage = ({ data }) => { if (data.id === latest.current) setResult(data) }
    thread.onerror = () => setResult({ error: '计算组件未能启动' })
    return () => { worker.current = null; thread.terminate() }
  }, [])
  useEffect(() => {
    const id = ++latest.current
    worker.current?.postMessage({ id, expression: block.expression, parameters: block.parameters, x: block.x, values })
  }, [block, values])
  const axis = block.parameters.find(p => p.name === block.x)
  const options = useMemo(() => {
    if (!colors || !result?.points?.some(([, y]) => y !== null)) return null
    return {
      animation: false, backgroundColor: colors.paper, color: [colors.accent], aria: { enabled: true },
      grid: { top: 34, bottom: 58, left: 66, right: 24 },
      tooltip: { trigger: 'axis', renderMode: 'richText', confine: true, valueFormatter: val => typeof val === 'number' ? precision(val) : '未定义' },
      xAxis: { type: 'value', min: axis.min, max: axis.max, name: [axis.label, axis.unit].filter(Boolean).join(' / '), nameLocation: 'middle', nameGap: 31, nameTextStyle: { color: colors.ink }, axisLabel: { color: colors.ink, formatter: precision } },
      yAxis: { type: 'value', scale: true, name: block.y_unit, nameTextStyle: { color: colors.ink }, axisLabel: { color: colors.ink, formatter: precision }, splitLine: { lineStyle: { color: colors.line } } },
      series: [
        { type: 'line', data: result.points, showSymbol: result.points.length < 14, connectNulls: false },
        ...(result.current !== null ? [{ type: 'scatter', data: [[result.xValue, result.current]], symbolSize: 10, z: 4 }] : []),
      ],
    }
  }, [result, block.y_unit, axis, colors])
  return <div className="research-component research-explore">
    <BlockHeader title={block.title || '参数探索'}><span className="research-pill">按公式试算</span>
      {state.values && <button type="button" className="research-action" onClick={() => change({ values: null })}>重置参数</button>}
    </BlockHeader>
    <LatexMath math={block.latex} displayMode />
    <div className="research-parameter-grid">
      {block.parameters.map(p => <ParameterInput key={p.name} parameter={{ ...p, domId: instanceId + '-' + p.name }} value={values[p.name]}
        onChange={value => change({ values: { ...values, [p.name]: value } })} />)}
    </div>
    {result?.error ? <div className="research-local-error" role="status">{result.error}
      <button type="button" className="research-action" onClick={onRepair}>重试试算</button></div> :
      <div className="research-calculated" aria-live="polite">
        <span><LatexText text={block.y_label} /></span>
        <strong>{!result ? '计算中' : result.current === null ? '在此处未定义' : precision(result.current)}</strong>
        {result?.current != null && <span>{block.y_unit}</span>}
      </div>}
    {options && <ChartCanvas options={options} label={(block.title || '参数') + '试算曲线'} dark={dark} />}
    {!result?.error && <footer className="research-block-foot"><button type="button" className="research-action"
      onClick={() => onAsk({ values, prompt: '请解释当前参数设置下的结果。' })}>解释当前取值</button></footer>}
  </div>
}
