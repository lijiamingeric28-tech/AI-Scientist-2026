import { extractionLabel, sourceName } from './readableData.js'
import { journalLabel } from './journal.js'

// Search the identifiers and the labels already shown by the UI. This does not
// group properties, translate scientific text, or infer any record associations.
export function matchesRecordSearch(record, query, source, propertyLabel = value => value) {
  const text = String(query ?? '').trim().toLocaleLowerCase()
  if (!text) return true
  return [record.entity_name, record.field_name, propertyLabel(record.field_name),
    record.field_value, record.field_unit, record.source_id, sourceName(source, record.source_id),
    journalLabel(record.source_id), source?.journal, source?.year,
    record.extraction_method, extractionLabel(record.extraction_method)]
    .some(value => value != null && String(value).toLocaleLowerCase().includes(text))
}
