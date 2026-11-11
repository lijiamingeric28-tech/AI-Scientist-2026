export const stateKey = (messageId, blockId) => 'astroquery.answer.v1.' + messageId + '.' + blockId

export function readState(key) {
  try { return JSON.parse(localStorage.getItem(key)) || {} } catch { return {} }
}

export function savedAnswerSelection(messages) {
  const records = [], parameters = []
  for (const message of [...messages].reverse().slice(0, 6)) {
    for (const block of [...(message.answer?.blocks || [])].reverse()) {
      const state = readState(stateKey(message.id, block.id))
      if (state.recordIds?.length) records.push({ ids: state.recordIds, time: state.touchedAt || 0 })
      if (block.type === 'explore' && state.values) parameters.push({
        selection: { message_id: message.id, block_id: block.id, values: state.values },
        time: state.touchedAt || 0,
      })
    }
  }
  records.sort((a, b) => b.time - a.time)
  parameters.sort((a, b) => b.time - a.time)
  return { recordIds: records[0]?.ids.slice(0, 40) || [], selections: parameters[0] ? [parameters[0].selection] : [] }
}
