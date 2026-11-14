import { useEffect, useRef, useState } from 'react'
import { titleText } from '@/lib/researchDisplay'

const EMPTY = { records: {}, figures: {} }

export function workbenchSelectionKey(taskId, deliveryId, revision) {
  return taskId && deliveryId && Number.isInteger(revision) && revision > 0
    ? `astroquery.results.selection.v2.${JSON.stringify([taskId, deliveryId, revision])}` : null
}

export function useWorkbenchSelection(taskId, deliveryId, revision) {
  const key = workbenchSelectionKey(taskId, deliveryId, revision)
  const activeKey = useRef(key)
  activeKey.current = key
  const [stored, setStored] = useState({ key: null, items: EMPTY })
  useEffect(() => {
    let items = EMPTY
    try {
      const parsed = key ? JSON.parse(localStorage.getItem(key)) : null
      if (parsed?.records && parsed?.figures) items = parsed
    } catch { /* Selection remains usable when local storage is unavailable. */ }
    setStored({ key, items })
  }, [key])
  const items = stored.key === key ? stored.items : EMPTY
  useEffect(() => {
    if (key && stored.key === key) {
      try { localStorage.setItem(key, JSON.stringify(stored.items)) } catch { /* Optional browser persistence. */ }
    }
  }, [stored, key])
  const idsOf = (kind, row) => kind === 'records' ? row.record_id : row.figure_id
  const toggle = (kind, rows) => setStored(previous => {
    if (!key || activeKey.current !== key) return previous
    const base = previous.key === key ? previous.items : EMPTY
    const next = { ...base[kind] }
    const valid = rows.filter(row => idsOf(kind, row))
    const removing = valid.every(row => next[idsOf(kind, row)])
    for (const row of valid) {
      const id = idsOf(kind, row)
      if (removing) delete next[id]
      else if (!next[id]) {
        next[id] = { id, title: kind === 'records'
          ? [row.field_name, [row.field_value, row.field_unit].filter(Boolean).join(' ')].filter(Boolean).join(' · ')
          : [row.label || '研究图像', row.page ? '第 ' + row.page + ' 页' : null].filter(Boolean).join(' · '),
        source: row.source_title ? titleText({ title: row.source_title }) : null, sourceId: row.source_id }
      }
    }
    return { key, items: { ...base, [kind]: next } }
  })
  const remove = (kind, id) => setStored(previous => {
    if (!key || activeKey.current !== key || previous.key !== key) return previous
    const next = { ...previous.items[kind] }
    delete next[id]
    return { ...previous, items: { ...previous.items, [kind]: next } }
  })
  const restore = entries => setStored(previous => {
    if (!key || activeKey.current !== key) return previous
    const base = previous.key === key ? previous.items : EMPTY
    const next = { records: { ...base.records }, figures: { ...base.figures } }
    for (const { kind, item } of entries) next[kind][item.id] ||= item
    return { key, items: next }
  })
  return { items, scope: {taskId,deliveryId,revision}, has: (kind, id) => Object.hasOwn(items[kind], id), toggle, remove, restore,
    clear: () => setStored(previous => key && activeKey.current === key ? { key, items: EMPTY } : previous),
    measurementIds: Object.keys(items.records), figureIds: Object.keys(items.figures) }
}
