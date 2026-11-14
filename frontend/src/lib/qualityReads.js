export function qualityResources(section) {
  return ({
    overview:['quality','sourceList'],
    trace:['quality','sourceList'],
    comparison:['quality','sourceList','analysisRecords','differences','matrix','reviewActivity'],
  })[section] || []
}
