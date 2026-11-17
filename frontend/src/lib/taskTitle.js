// Both task heading and sidebar use backend provenance; older APIs remain readable.
export function isCustomTitle(task, question) {
  if (task?.title_origin === 'custom') return true
  if (task?.title_origin === 'auto') return false
  if (!task?.title || !question) return false
  return task.title !== question && task.title !== Array.from(question).slice(0, 120).join('')
}

export function taskTitle(task, identity) {
  return (!isCustomTitle(task, identity?.question) && identity?.target) || task?.title || task?.query || ''
}
