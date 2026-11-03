const ACTIONS = { confirm: '确认当前解释', correct: '依据原件修正解释', not_supported: '原件不支持当前解释', unable: '证据不足，暂不判断' }

export function reviewReceipt(review, lifecycle) {
  const answer = review.answer
  if (!answer || typeof answer !== 'object') return null
  const application = review.application
  const applied = application?.status === 'applied'
  const unresolved = applied && (application.postcheck === 'unresolved' || answer.action === 'unable')
  const different = answer.comparison_outcome === 'different_conditions'
  return {
    question: review.question,
    answer: review.choices?.find(choice => choice.action === answer.action)?.label || ACTIONS[answer.action] || answer.action,
    reason: answer.reason,
    simulation: answer.simulation === true,
    status: applied ? '答案已保存并复检' : application ? '答案已保存，应用结果见详情' : '答案已保存，等待责任模块复检',
    outcome: unresolved ? '保留未决' : applied && different ? '按不同测量条件保留' : applied ? '已应用并复检' : '',
    continuation: applied ? lifecycle === 'completed' ? '查询已完成' : ['paused', 'interrupted'].includes(lifecycle) ? '任务当前已暂停，复检结果已保存。' : '继续查询' : '',
  }
}
