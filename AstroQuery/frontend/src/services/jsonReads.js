const cancelled=()=>new DOMException('The read was cancelled','AbortError')
function canonicalUrl(value){const url=new URL(value,'http://local.invalid');url.searchParams.sort();return String(value).startsWith('http')?url.href:url.pathname+url.search}
async function decode(response){
  if(!response.ok){let detail;try{detail=(await response.json()).detail}catch{detail=response.statusText}
    const error=new Error(typeof detail==='string'?detail:detail?.message||JSON.stringify(detail)||`HTTP ${response.status}`)
    error.code=detail?.code;error.status=response.status;error.details=detail;throw error}
  return response.json()
}

export function createJsonReads(fetcher,{maxEntries=48}={}){
  const pending=new Map(),cache=new Map();let epoch=0
  const invalidate=()=>{epoch++;cache.clear();pending.clear()}
  const remember=(key,value)=>{cache.delete(key);cache.set(key,value);while(cache.size>maxEntries)cache.delete(cache.keys().next().value)}
  async function load(url,options,key,signal,generation,retainBody){
    const cached=retainBody&&cache.get(key),headers=new Headers(options.headers)
    if(cached?.etag)headers.set('If-None-Match',cached.etag)
    let result=await fetcher(url,{...options,headers,signal})
    if(result.status===304){
      if(cached){if(generation===epoch)remember(key,cached);return cached.body}
      headers.delete('If-None-Match');result=await fetcher(url,{...options,headers,signal})
      if(result.status===304)throw new Error('304响应没有对应的本地副本')
    }
    const body=await decode(result),etag=result.headers?.get?.('ETag')
    if(retainBody&&etag&&!signal.aborted&&generation===epoch)remember(key,{etag,body})
    return body
  }
  return {invalidate,request(url,options={}){
    const {retainBody=true,...httpOptions}=options
    const method=(options.method||'GET').toUpperCase()
    if(method!=='GET')return fetcher(url,httpOptions).then(decode).then(value=>{invalidate();return value})
    if(options.signal?.aborted)return Promise.reject(cancelled())
    const normalized=canonicalUrl(url),headers=[...new Headers(options.headers)].sort(),key=JSON.stringify([normalized,headers,options.credentials||'same-origin',retainBody])
    let entry=pending.get(key)
    if(!entry||entry.controller.signal.aborted){
      const controller=new AbortController(),generation=epoch
      entry={controller,subscribers:new Set(),settled:false}
      entry.promise=Promise.resolve().then(()=>{if(controller.signal.aborted)throw cancelled();return load(normalized,httpOptions,key,controller.signal,generation,retainBody)}).finally(()=>{entry.settled=true;if(pending.get(key)===entry)pending.delete(key)})
      pending.set(key,entry)
    }
    return new Promise((resolve,reject)=>{
      const subscriber={};entry.subscribers.add(subscriber)
      const clean=()=>{entry.subscribers.delete(subscriber);options.signal?.removeEventListener('abort',abort)}
      const abort=()=>{clean();reject(cancelled());if(!entry.settled&&!entry.subscribers.size){entry.controller.abort();if(pending.get(key)===entry)pending.delete(key)}}
      options.signal?.addEventListener('abort',abort,{once:true})
      entry.promise.then(value=>{if(!options.signal?.aborted){clean();resolve(value)}},error=>{if(!options.signal?.aborted){clean();reject(error)}})
    })
  }}
}
