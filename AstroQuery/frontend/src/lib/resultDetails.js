// A measurement ID is not a version identity. Historical answers and current
// result pages can contain the same ID with different scientific values.
const sameScope=(taskId,deliveryId,revision,scope)=>taskId===scope.taskId&&deliveryId===scope.deliveryId&&revision===scope.revision
export function scopedRecordReference(records, recordId, scope) {
  return records.find(record => record.record_id===recordId &&
    sameScope(record.task_id || record.source?.task_id,record.delivery_id,record.delivery_revision,scope)) || {
    record_id:recordId,task_id:scope.taskId,delivery_id:scope.deliveryId,
    delivery_revision:scope.revision,details_loaded:false,
  }
}
export function scopedDrawerResources(data,scope) {
  return sameScope(data.taskId,data.deliveryId,data.deliveryRevision,scope) && (data.atSeq??null)===(scope.atSeq??null) && Boolean(data.sealedOnly)===Boolean(scope.sealedOnly)?data.resources:{}
}
