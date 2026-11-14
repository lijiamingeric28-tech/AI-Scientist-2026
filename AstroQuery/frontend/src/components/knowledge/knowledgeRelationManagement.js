import { knowledgeLinkIds } from './knowledgeReading.js'

export const incomingKnowledgeRelations = item => (item.relations?.related || [])
  .filter(relation => ['incoming', 'both'].includes(relation.direction) && !relation.unavailable)

export function createRelationDraft(item) {
  return { relatedIds: knowledgeLinkIds(item.related_ids, item.id), unlinkIncomingIds: [] }
}

const sameIds = (left, right) => left.length === right.length && left.every(id => right.includes(id))
export function relationDraftChanged(item, draft) {
  return !sameIds(knowledgeLinkIds(item.related_ids, item.id), knowledgeLinkIds(draft.relatedIds, item.id)) || draft.unlinkIncomingIds.length > 0
}

function validateSnapshot(item) {
  if (!item?.id || !Number.isInteger(item.revision) || item.revision < 0
    || !Number.isInteger(item.library_revision) || item.library_revision < 0) throw new Error('缺少有效修订，请重新读取知识关联')
  if (!Array.isArray(item.related_ids) || !Array.isArray(item.relations?.related)
    || item.related_ids.some(id => typeof id !== 'string' || !id.trim())
    || item.relations.related.some(relation => typeof relation?.id !== 'string' || !relation.id.trim())) throw new Error('知识关联响应不完整，请重新读取')
}

export function buildRelationPayload(item, draft) {
  validateSnapshot(item)
  const relatedIds = knowledgeLinkIds(draft.relatedIds, item.id)
  if (relatedIds.length > 100) throw new Error('关联知识最多选择 100 项')
  const incomingIds = incomingKnowledgeRelations(item).map(relation => relation.id)
  const unlinkIds = knowledgeLinkIds(draft.unlinkIncomingIds, item.id)
  if (unlinkIds.some(id => !incomingIds.includes(id))) throw new Error('传入关联已发生变化，请重新读取后核对')
  return { related_ids: relatedIds, unlink_incoming_ids: unlinkIds,
    expected_revision: item.revision, expected_library_revision: item.library_revision }
}

export function rebaseRelationDraft(base, draft, latest) {
  validateSnapshot(latest)
  if (latest.id !== base.id || latest.revision < base.revision || latest.library_revision < base.library_revision) throw new Error('最新关联与当前条目不匹配，请重新读取')
  const previous = knowledgeLinkIds(base.related_ids, base.id), selected = knowledgeLinkIds(draft.relatedIds, base.id)
  const removed = previous.filter(id => !selected.includes(id))
  const added = selected.filter(id => !previous.includes(id))
  const incomingIds = incomingKnowledgeRelations(latest).map(relation => relation.id)
  return { relatedIds: [...new Set([...knowledgeLinkIds(latest.related_ids, latest.id).filter(id => !removed.includes(id)), ...added])],
    unlinkIncomingIds: draft.unlinkIncomingIds.filter(id => incomingIds.includes(id)) }
}

export function relationMutationResult(result, id) {
  if (result?.success !== true || result.id !== id || result.entry?.id !== id
    || !Number.isInteger(result.revision) || !Number.isInteger(result.library_revision)
    || result.entry.revision !== result.revision || result.entry.library_revision !== result.library_revision
    || !Array.isArray(result.entry.related_ids) || !Array.isArray(result.entry.relations?.related)
    || !Array.isArray(result.affected_ids)) throw new Error('服务器未确认关联保存，请重新读取后重试')
  return result
}
