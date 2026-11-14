const BASE = '/registry-workbench'
const id = encodeURIComponent
const query = filters => new URLSearchParams(Object.entries(filters || {}).filter(([k,v]) => v != null && v !== '' && !(v === 'all' && ['origin','status','type_id','family_id'].includes(k)))).toString()

export function createRegistryApi(request) {
  const read = (path, filters, options) => { const q = query(filters); return request(`${BASE}${path}${q ? `?${q}` : ''}`, options) }
  const write = async (path, method, body) => {
    const result = await request(`${BASE}${path}`, {method, body:JSON.stringify(body)})
    if (result?.success !== true) throw new Error('服务未返回成功回执，操作状态未确认；请重新读取。')
    return result
  }
  return {
    summary: (filters, options) => read('/summary',filters,options),
    list: (kind,filters,options) => read(`/${kind}`,filters,options),
    detail: (kind,key,filters,options) => read(`/${kind}/${id(key)}`,filters,options),
    graph: (filters,options) => read('/graph',filters,options),
    knowledge: (entry,filters,options) => read(`/knowledge/${id(entry)}`,filters,options),
    workspaces: ({projection,...options}={}) => read('/workspaces',{projection},options),
    workspace: (key,options) => read(`/workspaces/${id(key)}`,null,options),
    createWorkspace: (base_bundle_id) => write('/workspaces','POST',base_bundle_id ? {base_bundle_id} : {}),
    save: (workspace,kind,key,body,revision) => write(`/workspaces/${id(workspace)}/${kind}${key ? `/${id(key)}` : ''}`,key ? 'PUT' : 'POST',{...body,expected_revision:revision}),
    remove: (workspace,kind,key,revision) => write(`/workspaces/${id(workspace)}/${kind}/${id(key)}`,'DELETE',{expected_revision:revision}),
    impact: (workspace,kind,key,options) => read(`/workspaces/${id(workspace)}/${kind}/${id(key)}/impact`,null,options),
    validate: async (workspace,revision) => {
      const result=await request(`${BASE}/workspaces/${id(workspace)}/validate`,{method:'POST',body:JSON.stringify({expected_revision:revision})})
      if(typeof result?.success!=='boolean'||!result.validation?.id||!['passed','failed'].includes(result.validation.state)||result.success!==(result.validation.state==='passed'))throw new Error('校验服务未返回有效回执')
      return result
    },
    publish: (workspace,body) => write(`/workspaces/${id(workspace)}/publish`,'POST',body),
    releases: ({projection,...options}={}) => read('/releases',{projection},options),
    activate: (release,body) => write(`/releases/${id(release)}/activate`,'POST',body),
  }
}
