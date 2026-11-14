import { useEffect, useState } from 'react'
import { getRecordsPage } from '@/services/api'
import { resultPageKey } from '@/services/resultPages'

// A page belongs to one exact delivery/query. Late and aborted reads cannot
// repaint another page, and previous-page data is never presented as complete.
export function useRecordsPage(scope, query, enabled = true) {
  const key=resultPageKey(scope,query)
  const initial=scope?.initialPage?.request_key===key?scope.initialPage:null
  const [result,setResult]=useState(null), [retry,setRetry]=useState(0)
  useEffect(()=>{
    if(!enabled || !scope?.deliveryId || (initial && !retry)) return
    const controller=new AbortController()
    setResult({key,status:'settling',data:null})
    getRecordsPage(scope.taskId,scope.deliveryId,scope.revision,query,{signal:controller.signal,atSeq:scope.atSeq,sealedOnly:scope.sealedOnly}).then(data=>{
      if(!controller.signal.aborted)setResult({key,status:'success',data})
    }).catch(error=>{if(!controller.signal.aborted)setResult({key,status:'error',data:null,error:error.message})})
    return ()=>controller.abort()
  },[key,enabled,retry])
  return {...(result?.key===key?result:initial?{status:'success',data:initial}:{status:'settling',data:null}),reload:()=>setRetry(n=>n+1)}
}
