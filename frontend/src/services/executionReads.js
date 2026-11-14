const cancelled=()=>new DOMException('Execution read cancelled','AbortError')
const copy=value=>structuredClone(value)

export function createExecutionReads(loader,{maxEntries=32,maxBytes=4*1024*1024,maxAge=30000}={}) {
  const cache=new Map(),pending=new Map();let bytes=0
  const remove=key=>{const old=cache.get(key);if(old){bytes-=old.size;cache.delete(key)}}
  return {read(taskId,query={},options={}) {
    if(options.signal?.aborted)return Promise.reject(cancelled())
    const {readVersion=0,...http}=options
    const key=JSON.stringify([taskId,Object.entries(query).filter(([,v])=>v!=null).sort(([a],[b])=>a.localeCompare(b)),readVersion])
    const cached=cache.get(key)
    if(cached&&Date.now()-cached.at<maxAge){cache.delete(key);cache.set(key,cached);return Promise.resolve(copy(cached.value))}
    remove(key)
    let entry=pending.get(key)
    if(!entry||entry.controller.signal.aborted){
      const controller=new AbortController()
      entry={controller,subscribers:new Set(),settled:false}
      entry.promise=Promise.resolve().then(()=>{
        if(controller.signal.aborted)throw cancelled()
        return loader(taskId,query,{...http,signal:controller.signal})
      }).then(value=>{
        if(controller.signal.aborted)throw cancelled()
        if(query.at_seq!=null){
          const size=new TextEncoder().encode(JSON.stringify(value)).length
          if(size<=maxBytes){remove(key);cache.set(key,{value:copy(value),size,at:Date.now()});bytes+=size
            while(cache.size>maxEntries||bytes>maxBytes)remove(cache.keys().next().value)}
        }
        return value
      }).finally(()=>{entry.settled=true;if(pending.get(key)===entry)pending.delete(key)})
      pending.set(key,entry)
    }
    return new Promise((resolve,reject)=>{
      const subscriber={};entry.subscribers.add(subscriber)
      const clean=()=>{entry.subscribers.delete(subscriber);options.signal?.removeEventListener('abort',abort)}
      const abort=()=>{clean();reject(cancelled());if(!entry.settled&&!entry.subscribers.size){entry.controller.abort();if(pending.get(key)===entry)pending.delete(key)}}
      options.signal?.addEventListener('abort',abort,{once:true})
      entry.promise.then(value=>{clean();if(!options.signal?.aborted)resolve(copy(value))},error=>{clean();reject(error)})
    })
  }}
}
