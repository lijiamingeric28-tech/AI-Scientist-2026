const id = encodeURIComponent
const FILTERS = ['q','quick','field','fields','source_id','source_group','year_sort','record_id']
export function filteredSelection(filters, excluded = []) {
  return { mode:'filtered', filter_version:1, filters:Object.fromEntries(FILTERS.filter(key => filters[key] != null).map(key => [key, filters[key]])), excluded_measurement_ids:[...excluded] }
}
export const previewReadKey = task => task?.preview_revision ?? task?.core_event_cursor
export function resultPageKey(scope, query = {}) {
  const normalized={q:'',quick:'target',field:'all',source_id:'all',source_group:'all',year_sort:'none',offset:0,limit:50,collapse_duplicates:true,...query,...(scope?.atSeq!=null?{at_seq:scope.atSeq}:{}),...(scope?.sealedOnly?{sealed_only:true}:{})}
  delete normalized.view
  return JSON.stringify([scope?.taskId,scope?.deliveryId,scope?.revision,Object.fromEntries(Object.entries(normalized).filter(([,v])=>v!=null).sort(([a],[b])=>a.localeCompare(b)))])
}
export function createResultPages(request) {
  return {
    async readResourcePage(taskId, deliveryId, name, revision, query = {}, options) {
      if (!deliveryId) throw new Error('读取结果必须指定交付版本')
      const params=new URLSearchParams(Object.entries({offset:0,limit:50,...query,...(revision?{expected_delivery_revision:revision,delivery_revision:revision}:{})}).filter(([,value])=>value!=null).map(([key,value])=>[key,Array.isArray(value)?JSON.stringify(value):value]))
      const page=await request(`/tasks/${id(taskId)}/deliveries/${id(deliveryId)}/${name}?${params}`,options)
      if (page.delivery_id!==deliveryId) throw new Error('结果响应的交付版本不一致')
      if (revision && page.delivery_revision!==revision) throw new Error('结果响应的交付修订不一致')
      return page
    },
    async getPreview(taskId, options, query = {}) {
      const params=new URLSearchParams({view:'ui',preview_protocol:2,offset:0,limit:50,...query})
      const page=await request(`/tasks/${id(taskId)}/preview?${params}`, options)
      if(query.expected_preview_id && page.preview_id!==query.expected_preview_id) throw new Error('临时数据已有更新，请重新读取')
      return {...page,offset:Number(params.get('offset')),limit:Number(params.get('limit'))}
    },
  }
}
