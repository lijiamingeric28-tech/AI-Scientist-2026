// Bump when the material UI projection/adaptation contract changes.
export const WORKBENCH_CACHE_PROTOCOL = 'material-workbench/3'
const cancelled = () => new DOMException('The read was cancelled', 'AbortError')
const copy = value => structuredClone(value)

// A write can invalidate transport while its consumer remains active. Restart
// only that explicit condition, once per increasing epoch; real errors and a
// consumer's own abort keep their normal behavior.
export async function readCurrentWorkbench(read, signal) {
  let restartedEpoch = -1
  for (;;) {
    if (signal?.aborted) throw cancelled()
    try { return await read() }
    catch (error) {
      if (signal?.aborted || error.name !== 'AbortError' ||
          !Number.isInteger(error.invalidationEpoch) || error.invalidationEpoch <= restartedEpoch) throw error
      restartedEpoch = error.invalidationEpoch
    }
  }
}

export function workbenchQuery(scope, query = {}) {
  return Object.fromEntries(Object.entries({
    ...query,
    ...(scope.atSeq != null ? {at_seq:scope.atSeq} : {}),
    ...(scope.sealedOnly ? {sealed_only:true} : {}),
  }).filter(([,value]) => value != null && value !== '' && value !== 'all').sort(([a],[b]) => a.localeCompare(b)))
}

export function workbenchReadKey(scope, name, query = {}) {
  return JSON.stringify([scope.taskId, scope.deliveryId, scope.revision,
    scope.protocol || WORKBENCH_CACHE_PROTOCOL, name, workbenchQuery(scope, query)])
}

export function createWorkbenchReads(loader, {maxEntries = 32, maxBytes = 8 * 1024 * 1024} = {}) {
  const cache = new Map(), pending = new Map(), encoder = new TextEncoder()
  let bytes = 0, epoch = 0
  const remove = key => { const entry=cache.get(key); if(entry) bytes-=entry.bytes; cache.delete(key) }
  const remember = (key, value, name, query) => {
    const stored = copy(value)
    // A live summary belongs to its observation time, not to the static delivery.
    if (name === 'materials' && query.material_id && query.at_seq == null && !query.sealed_only)
      for (const item of stored.items || []) delete item.summary
    const size = encoder.encode(JSON.stringify(stored)).byteLength
    remove(key)
    if (size > maxBytes) return
    cache.set(key, {value:stored,bytes:size}); bytes += size
    while (cache.size > maxEntries || bytes > maxBytes) remove(cache.keys().next().value)
  }
  const invalidate = () => {
    epoch++; cache.clear(); bytes=0
    const reason=Object.assign(cancelled(),{invalidationEpoch:epoch})
    for (const entry of pending.values()) entry.controller.abort(reason)
    pending.clear()
  }
  return {invalidate, read(scope, name, input = {}, options = {}) {
    if (options.signal?.aborted) return Promise.reject(cancelled())
    const query = workbenchQuery(scope, input)
    const key = JSON.stringify([workbenchReadKey(scope,name,query),[...new Headers(options.headers)].sort(),options.credentials || 'same-origin'])
    const cacheable = query.projection !== 'summary'
    const cached = cacheable && !options.revalidate && cache.get(key)
    if (cached) { cache.delete(key); cache.set(key,cached); return Promise.resolve(copy(cached.value)) }
    let entry = pending.get(key)
    if (!entry || entry.controller.signal.aborted) {
      const controller = new AbortController(), generation = epoch
      entry = {controller, subscribers:new Set(), settled:false}
      entry.promise = Promise.resolve().then(() => {
        if (controller.signal.aborted) throw cancelled()
        return loader(scope,name,query,{...options,signal:controller.signal})
      }).then(value => {
        if (controller.signal.aborted || generation !== epoch) throw controller.signal.reason || cancelled()
        if (cacheable) remember(key,value,name,query)
        return value
      }).finally(() => { entry.settled=true; if(pending.get(key)===entry) pending.delete(key) })
      pending.set(key,entry)
    }
    return new Promise((resolve,reject) => {
      const subscriber = {}; entry.subscribers.add(subscriber)
      const clean = () => {
        entry.subscribers.delete(subscriber)
        options.signal?.removeEventListener('abort',abort)
        entry.controller.signal.removeEventListener('abort',invalidated)
      }
      const invalidated = () => { clean(); reject(entry.controller.signal.reason || cancelled()) }
      const abort = () => {
        clean(); reject(cancelled())
        if (!entry.settled && !entry.subscribers.size) {
          entry.controller.abort()
          if (pending.get(key) === entry) pending.delete(key)
        }
      }
      options.signal?.addEventListener('abort',abort,{once:true})
      entry.controller.signal.addEventListener('abort',invalidated,{once:true})
      entry.promise.then(value => { clean(); if (!options.signal?.aborted) resolve(copy(value)) },error => { clean(); reject(error) })
    })
  }}
}
