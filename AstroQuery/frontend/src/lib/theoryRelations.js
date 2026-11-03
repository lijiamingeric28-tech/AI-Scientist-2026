// Only reviewed, applicable bindings explicitly covering two properties become
// an edge. Multi-variable laws do not generate an invented pairwise clique.
export function theoryRelations(report) {
  return (report?.theory || []).filter(item => ['physical_law', 'empirical_relation'].includes(item.kind)
    && ['conditional_background', 'applicable_background'].includes(item.scope)
    && new Set(item.property_ids || []).size === 2
    && item.entry_ref?.content_sha256 && item.claim?.statement_zh).map(item => {
      const ids = [...new Set(item.property_ids)]
      const conditions = (item.conditions || []).map(condition => `${condition.key}：${condition.equals ?? condition.value ?? '请核对原文条件'}`).join('；')
      return { field_a: ids[0], field_b: ids[1],
        description: [item.claim.statement_zh, conditions && `适用条件：${conditions}`, item.scope === 'conditional_background' && '本任务条件尚不齐全，仅作有条件理论背景。', ...(item.limitations || [])].filter(Boolean).join('\n\n'),
        kb_references: (item.sources || []).map(source => ({ title: source.identity?.title || source.title || source.source_id, url: source.identity?.url || source.url, source: source.identity?.citation })),
        claim_id: item.claim.claim_id, scope: item.scope }
    })
}
