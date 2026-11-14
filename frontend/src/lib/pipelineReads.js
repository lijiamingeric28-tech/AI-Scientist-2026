export async function readPipelineSnapshot(api,{id,conversation=true,player=false,seq,frame,signal}){
  const options={signal};let state,presentation
  if(player){state={task_id:id,revision:0};presentation=frame||await api.getPresentation(id,seq,options)}
  else {
    state=conversation?await api.getChatState(id,options):await api.getWorkspaceState(id,options)
    presentation=state.presentation
    if(presentation&&state.core_event_cursor!=null&&state.kind!=='legacy'&&!state.readOnly&&presentation.cursor!==state.core_event_cursor)
      throw new Error('任务状态与展示游标不一致，请重新读取')
    if(!presentation)presentation=await api.getPresentation(id,null,options)
  }
  return {...state,presentation,messages:state.messages||presentation.messages||[],stages:state.stages||presentation.stages||[]}
}
