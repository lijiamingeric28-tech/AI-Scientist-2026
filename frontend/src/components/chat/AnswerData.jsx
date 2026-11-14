import { useMemo, useState } from 'react'
import { Icon } from '@/components/icons'
import { LatexText } from '@/components/results/LatexMath'

export const columnNames = {
  property: '性质', original: '原报', value: '显示值', unit: '单位', error: '原报误差',
  method: '方法', conditions: '测量条件', source: '来源', year: '年份',
}
const baseColumns = ['original', 'error', 'conditions', 'source']
const numeric = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })

export const recordText = row => [row.original, row.original_unit].filter(Boolean).join(' ')
export const cellText = (row, key) => key === 'original' ? recordText(row) :
  key === 'error' ? row.error || '未报' : row[key] ?? ''

export function BlockHeader({ title, children }) {
  return <header className="research-block-head">{title && <h3>{title}</h3>}
    {children && <div className="research-controls">{children}</div>}</header>
}

export function CiteButton({ id, onCite, children, className = '', title }) {
  return id ? <button type="button" data-citation-id={id} className={'research-ref ' + className} onClick={() => onCite(id)} title={title}>{children}</button> :
    <span className={className} title={title}>{children}</span>
}

export function useCopy() {
  const [status, setStatus] = useState('')
  async function copy(value) {
    try {
      await navigator.clipboard.writeText(value)
      setStatus('已复制')
    } catch {
      setStatus('复制失败')
    }
  }
  return [status, copy]
}

function TableContents({ columns, rows, selection, onSelect, onCite, sort, onSort }) {
  return <div className="research-table-scroll" tabIndex={0} aria-label="测量表格，可横向滚动">
    <table className="research-table">
      <thead><tr>{onSelect && <th scope="col" className="research-check-cell"><span className="sr-only">选中</span></th>}
        {columns.map(key => <th key={key} scope="col" aria-sort={sort?.key === key ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
          {onSort ? <button type="button" onClick={() => onSort(key)}>{columnNames[key]}
            {sort?.key === key && (sort.dir === 1 ? <Icon.Send width={13} height={13} /> : <Icon.ChevronDown width={13} height={13} />)}
          </button> : columnNames[key]}
        </th>)}</tr></thead>
      <tbody>{rows.map(row => <tr key={row.id} data-selected={selection?.includes(row.id) || undefined}>
        {onSelect && <td className="research-check-cell"><input type="checkbox" checked={selection?.includes(row.id) || false}
          aria-label={'选中 ' + recordText(row) + ' ' + row.source} onChange={() => onSelect(row.id)} /></td>}
        {columns.map(key => {
          const value = cellText(row, key)
          return <td className={['value', 'unit', 'original', 'error', 'year'].includes(key) ? 'research-number' : ''} key={key}>
            {key === 'source' ? <CiteButton id={row.source_citation_id} onCite={onCite} title={row.source_title}>{value}</CiteButton>
              : ['original', 'value'].includes(key) ? <CiteButton id={row.citation_id} onCite={onCite} title="打开测量记录">{value || '—'}</CiteButton>
                : value === '' ? '—' : <LatexText text={String(value)} />}
          </td>
        })}
      </tr>)}</tbody>
    </table>
  </div>
}

export function AnswerTable({ block, state, change, onCite, onAsk, compact = false }) {
  const columns = useMemo(() => {
    const requested = [...new Set((block.columns || []).filter(key => columnNames[key]))]
    const keys = requested.length ? requested : baseColumns
    return keys.some(key => key === 'value' || key === 'original') ? keys : ['original', ...keys]
  }, [block.columns])
  const filter = state.filter || ''
  const selected = state.recordIds || []
  const sort = state.sort
  const rows = useMemo(() => {
    const search = filter.trim().toLocaleLowerCase()
    const matching = search ? block.rows.filter(row => columns.some(key => String(cellText(row, key)).toLocaleLowerCase().includes(search))) : block.rows
    if (!sort) return matching
    return [...matching].sort((a, b) => {
      if (['value', 'original', 'year'].includes(sort.key)) {
        const x = Number(sort.key === 'year' ? a.year : a.typed?.value)
        const y = Number(sort.key === 'year' ? b.year : b.typed?.value)
        if (Number.isFinite(x) && Number.isFinite(y) && x !== y) return sort.dir * (x - y)
      }
      return sort.dir * numeric.compare(String(cellText(a, sort.key)), String(cellText(b, sort.key)))
    })
  }, [block.rows, columns, filter, sort])
  const [copyStatus, copy] = useCopy()
  function copyTable() {
    const visible = selected.length ? rows.filter(row => selected.includes(row.id)) : rows
    const values = visible.map(row => columns.map(key => String(cellText(row, key)).replace(/[\t\r\n]+/g, ' ')).join('\t'))
    copy([columns.map(key => columnNames[key]).join('\t'), ...values].join('\n'))
  }
  function select(recordId) {
    change({ recordIds: selected.includes(recordId) ? selected.filter(id => id !== recordId) : [...selected, recordId] })
  }
  if (compact) return <TableContents columns={columns} rows={block.rows} onCite={onCite} />
  return <div className="research-component">
    <BlockHeader title={block.title || '测量记录'}>
      <label className="research-filter"><Icon.Search width={15} height={15} aria-hidden="true" />
        <input value={filter} onChange={e => change({ filter: e.target.value })} placeholder="筛选记录" aria-label="筛选记录" />
      </label>
      <button type="button" className="research-action" onClick={copyTable} disabled={!rows.length}><Icon.Copy width={15} height={15} />{copyStatus || '复制表格'}</button>
      {rows.length > 6 && <button type="button" className="research-action" aria-expanded={Boolean(state.expanded)}
        onClick={() => change({ expanded: !state.expanded })}><Icon.Maximize width={15} height={15} />{state.expanded ? '收起' : '展开'}</button>}
    </BlockHeader>
    {rows.length ? <TableContents columns={columns} rows={state.expanded ? rows : rows.slice(0, 6)}
      selection={selected} onSelect={select} onCite={onCite} sort={sort}
      onSort={key => change({ sort: { key, dir: sort?.key === key ? -sort.dir : 1 } })} /> :
      <p className="research-quiet" role="status">没有匹配的记录</p>}
    <footer className="research-block-foot">
      <span>{rows.length} 条{filter && '符合筛选'}{rows.length > 6 && !state.expanded && ' · 显示前 6 条'}</span>
      {selected.length > 0 && <button type="button" className="research-action" onClick={() => onAsk({
        recordIds: selected, prompt: selected.length === 1 ? '这条测量为什么不同？' : '这些测量之间有什么差别？',
      })}>就选中的 {selected.length} 条追问</button>}
      {selected.length === 1 && <CiteButton className="research-action" id={block.rows.find(row => row.id === selected[0])?.citation_id} onCite={onCite}>打开记录 <Icon.ExternalLink width={14} height={14} /></CiteButton>}
    </footer>
  </div>
}
