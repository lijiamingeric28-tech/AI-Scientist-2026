import {useEffect,useState} from 'react'
import {getWorkbenchPage} from '@/services/api'
import {workbenchReadKey} from '@/services/workbenchReads'

export function useAuditPage(scope,query,enabled) {
  const key=scope?workbenchReadKey(scope,'changes',query):'', [state,setState]=useState({}),[retry,setRetry]=useState(0)
  useEffect(()=>{
    if(!scope||!enabled)return
    const controller=new AbortController()
    getWorkbenchPage(scope.taskId,scope.deliveryId,scope.revision,'changes',query,{signal:controller.signal,revalidate:retry>0})
      .then(value=>{if(!controller.signal.aborted)setState({key,value})})
      .catch(error=>{if(!controller.signal.aborted)setState({key,error:error.message})})
    return()=>controller.abort()
  },[key,enabled,retry])
  return {...(state.key===key?state:{}),retry:()=>setRetry(n=>n+1)}
}
