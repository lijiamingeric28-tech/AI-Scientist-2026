import {useCallback,useEffect,useMemo,useRef,useState} from 'react'
import {request} from '@/services/api'
import {createRegistryApi} from '@/services/registryApi'
import {registryQuery,registryGraphQuery,registryWritable,canPublishRegistry,createRegistryReadCache,createRegistryOperationTokens,readRegistryEditorCatalog} from '@/lib/registryWorkbench'

export const registryApi=createRegistryApi(request)
const rows = data => Array.isArray(data) ? data : data?.items || data?.workspaces || data?.releases || []
function useRegistryRead(cache,key,loader,version,empty,active=true) {
  const loaderRef=useRef(loader);loaderRef.current=loader
  const [state,setState]=useState({key:null,data:empty,loading:true,error:'',stale:false})
  useEffect(()=>{
    if(!active)return
    const controller=new AbortController(),cached=cache.peek(key)
    setState({key,version,data:cached??empty,loading:!cache.fresh(key),error:'',stale:false})
    // Defer dispatch so cancelled StrictMode setups and rapid view changes do not issue a request.
    Promise.resolve().then(()=>{
      if(!controller.signal.aborted)return cache.read(key,()=>loaderRef.current(controller.signal),controller.signal)
    }).then(data=>{if(!controller.signal.aborted)setState({key,version,data,loading:false,error:'',stale:false})}).catch(e=>{if(!controller.signal.aborted)setState({key,version,data:cache.peek(key)??empty,loading:false,error:e.message,stale:true})})
    return()=>controller.abort()
  },[cache,key,version,active])
  if(!active)return {key,data:cache.peek(key)??empty,loading:false,error:'',stale:false}
  return state.key===key&&state.version===version?state:{key,data:cache.peek(key)??empty,loading:!cache.fresh(key),error:'',stale:false}
}
const EMPTY_LIST={items:[],total:0},EMPTY_GRAPH={nodes:[],edges:[],categories:[]}
export function useRegistryWorkbench() {
  const [filters,setFilters]=useState({keyword:'',type_id:'',family_id:'',origin:'',status:'',sort:'name'})
  const [keyword,setKeyword]=useState(''),[scope,setScope]=useState({}),[kind,setKind]=useState('properties')
  const [mode,setMode]=useState('graph'),[listMode,setListMode]=useState('cards'),[offset,setOffset]=useState(0),[limit,setLimit]=useState(50),[budget,setBudget]=useState(80)
  const [scene,setScene]=useState({view:'overview'}),[version,setVersion]=useState(0)
  const [mutationError,setError]=useState(''),[busy,setBusy]=useState(false),[conflict,setConflict]=useState(false)
  const [workspaces,setWorkspaces]=useState([]),[releases,setReleases]=useState([]),[validation,setValidation]=useState(null),[notice,setNotice]=useState('')
  const [directoryError,setDirectoryError]=useState(''),[versionsOpen,setVersionsOpen]=useState(false),[directoryLoading,setDirectoryLoading]=useState(false),[directoryRetry,setDirectoryRetry]=useState(0)
  const [selected,setSelected]=useState(null),[detail,setDetail]=useState(null),[detailLoading,setDetailLoading]=useState(false),[detailError,setDetailError]=useState('')
  const operation=useRef(false),publicationIds=useRef(createRegistryOperationTokens()),cacheRef=useRef(null)
  if(!cacheRef.current)cacheRef.current=createRegistryReadCache(48)
  useEffect(()=>{const timer=setTimeout(()=>{setFilters(f=>({...f,keyword}));setOffset(0)},250);return()=>clearTimeout(timer)},[keyword])
  const query=useMemo(()=>registryQuery({...filters,...scope,offset,limit},listMode),[filters,scope,offset,limit,listMode])
  const graphQuery=useMemo(()=>registryGraphQuery({...filters,...scope},scene,budget),[filters,scope,scene,budget])
  const reload=useCallback(()=>{cacheRef.current.invalidate();setVersion(n=>n+1)},[])
  const catalogScopeKey=JSON.stringify(scope)
  const loadEditorCatalog=useCallback(signal=>readRegistryEditorCatalog(registryApi,cacheRef.current,JSON.parse(catalogScopeKey),signal),[catalogScopeKey,version])
  const catalogQuery={...registryQuery(scope,'scope'),projection:'directory'},catalogKey=`summary:${JSON.stringify(catalogQuery)}`
  const catalogRead=useRegistryRead(cacheRef.current,catalogKey,signal=>registryApi.summary(catalogQuery,{signal}),version,null)
  // Ordering affects rows, not counts or the complete version directory.
  const hasSummaryFilters=Object.keys(registryQuery({...filters,sort:''},'scope')).length>0
  const summaryQuery={...registryQuery({...filters,...scope,sort:''},'scope'),projection:'stats'},summaryKey=`summary:${JSON.stringify(summaryQuery)}`
  const filteredSummary=useRegistryRead(cacheRef.current,summaryKey,signal=>registryApi.summary(summaryQuery,{signal}),version,null,hasSummaryFilters)
  const summaryRead=hasSummaryFilters?filteredSummary:catalogRead
  const listRead=useRegistryRead(cacheRef.current,`list:${kind}:${JSON.stringify(query)}`,signal=>registryApi.list(kind,query,{signal}),version,EMPTY_LIST,mode==='matrix')
  const graphRead=useRegistryRead(cacheRef.current,`graph:${JSON.stringify(graphQuery)}`,signal=>registryApi.graph(graphQuery,{signal}),version,EMPTY_GRAPH,mode==='graph')
  const data={summary:summaryRead.data,list:listRead.data,graph:graphRead.data}
  const visibleRead=mode==='graph'?graphRead:listRead
  const loading=summaryRead.loading||visibleRead.loading,stale=summaryRead.stale||visibleRead.stale,error=mutationError||summaryRead.error||visibleRead.error
  const matchedTotal=mode==='graph'?summaryRead.data?.counts?.[kind]:listRead.data.total
  useEffect(()=>{if(!versionsOpen)return;const c=new AbortController();setDirectoryLoading(true);Promise.resolve().then(()=>{if(c.signal.aborted)return;return Promise.all([registryApi.workspaces({projection:'directory',signal:c.signal}),registryApi.releases({projection:'directory',signal:c.signal})])}).then(result=>{if(!c.signal.aborted&&result){setWorkspaces(rows(result[0]));setReleases(rows(result[1]));setDirectoryError('')}}).catch(e=>{if(!c.signal.aborted)setDirectoryError(`版本目录读取失败：${e.message}`)}).finally(()=>{if(!c.signal.aborted)setDirectoryLoading(false)});return()=>c.abort()},[version,versionsOpen,directoryRetry])
  useEffect(()=>{
    if(!selected){setDetail(null);return}
    const c=new AbortController();setDetailLoading(true);setDetailError('');setDetail(null)
    registryApi.detail(selected.kind,selected.id,scope,{signal:c.signal}).then(result=>{if(!c.signal.aborted)setDetail(result.item||result)}).catch(e=>{if(!c.signal.aborted)setDetailError(e.message)}).finally(()=>{if(!c.signal.aborted)setDetailLoading(false)})
    return()=>c.abort()
  },[selected,scope,version])
  const run=async callback=>{
    if(operation.current)throw new Error('另一项操作正在进行')
    operation.current=true;setBusy(true);setError('');setNotice('')
    try{return await callback()}catch(e){setError(e.status===409?`版本冲突：${e.message}。表单内容已保留，请重新读取后比较再保存。`:e.message);if(e.status===409)setConflict(true);throw e}finally{operation.current=false;setBusy(false)}
  }
  const createDraft=()=>run(async()=>{
    if(stale||loading)throw new Error('请先重新读取当前版本')
    const result=await registryApi.createWorkspace(data.summary?.active_bundle?.id)
    if(!result.workspace?.id)throw new Error('草稿回执缺少工作区标识')
    setScope({workspace_id:result.workspace.id});setValidation(null);setConflict(false);reload();setNotice('已创建服务器草稿，仅发布后影响新任务');return result.workspace
  })
  const save=(entity,item,payload)=>run(async()=>{
    if(!registryWritable(data.summary,stale||loading,false)||conflict)throw new Error('当前版本不可写，请读取草稿后重试')
    const result=await registryApi.save(data.summary.workspace.id,entity,item?.id,payload,data.summary.workspace.revision)
    if(!result.workspace?.id||result.workspace.revision==null)throw new Error('保存回执缺少服务器工作区版本')
    setValidation(null);reload();setNotice('草稿已保存；需要重新校验与发布');return result
  })
  const remove=(entity,item)=>run(async()=>{
    if(!registryWritable(data.summary,stale||loading,false)||conflict)throw new Error('当前版本不可写')
    const result=await registryApi.remove(data.summary.workspace.id,entity,item.id,data.summary.workspace.revision)
    setValidation(null);setSelected(null);reload();setNotice('已保存禁用、移除或解绑结果；尚未发布');return result
  })
  const validate=()=>run(async()=>{
    if(!registryWritable(data.summary,stale||loading,false))throw new Error('请选择可写草稿')
    const result=await registryApi.validate(data.summary.workspace.id,data.summary.workspace.revision)
    if(!result.validation?.id)throw new Error('校验回执缺少标识')
    setValidation(result.validation);setNotice(result.validation.state==='passed'?'校验通过，请审阅影响后发布':'校验未通过，请检查问题');return result
  })
  const publish=()=>run(async()=>{
    if(!canPublishRegistry(data.summary,validation,stale||loading,false))throw new Error('请对当前草稿版本重新校验')
    const key=`publish:${data.summary.workspace.id}:${data.summary.workspace.revision}`
    const result=await registryApi.publish(data.summary.workspace.id,{expected_revision:data.summary.workspace.revision,validation_id:validation.id,expected_active_bundle_id:data.summary.active_bundle.id,idempotency_key:publicationIds.current.get(key)})
    publicationIds.current.ack(key)
    setScope({});setValidation(null);reload();setNotice('发布成功，已原子激活规范与知识版本；仅用于新任务');return result
  })
  const activate=release=>run(async()=>{
    if(stale||loading)throw new Error('请先重新读取活动版本')
    const key=`activate:${release.id}:${data.summary.active_bundle.id}`
    const result=await registryApi.activate(release.id,{expected_active_bundle_id:data.summary.active_bundle.id,idempotency_key:publicationIds.current.get(key)})
    publicationIds.current.ack(key)
    setScope({});setValidation(null);reload();setNotice('历史版本已激活，仅作用于新任务');return result
  })
  return {loadEditorCatalog,loadVersions:()=>{setVersionsOpen(true);if(directoryError)setDirectoryRetry(n=>n+1)},directoryLoading,types:catalogRead.data?.types||[],families:catalogRead.data?.families||[],familyDirectoryError:catalogRead.error,matchedTotal,filters,keyword,setKeyword,setFilter:(key,value)=>{setFilters(f=>({...f,[key]:value}));setOffset(0);setScene({view:'overview'})},kind,setKind:v=>{setKind(v);setOffset(0);setSelected(null)},mode,setMode,listMode,setListMode:v=>{if(v!==listMode){setListMode(v);setOffset(0)}},offset,setOffset,limit,setLimit:v=>{setLimit(v);setOffset(0)},budget,setBudget,scene,setScene,scope,setScope:v=>{setScope(v);setSelected(null);setOffset(0);setValidation(null);setConflict(false)},...data,loading,stale,error,busy,conflict,workspaces,releases,validation,notice:notice||directoryError,selected,setSelected,detail:selected&&detail?.id===selected.id?detail:null,detailLoading,detailError,reload:()=>{setConflict(false);setError('');reload()},createDraft,save,remove,validate,publish,activate,writable:registryWritable(data.summary,stale||loading||conflict,busy),canPublish:canPublishRegistry(data.summary,validation,stale||loading||conflict,busy)}
}
