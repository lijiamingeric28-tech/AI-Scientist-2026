const normalize = value => String(value ?? '').normalize('NFKC').toLocaleLowerCase().trim()

export function filterRegistryFamilies(families = [], keyword = '') {
  const terms = normalize(keyword).split(/\s+/).filter(Boolean)
  return families.filter(family => {
    const text = normalize(`${family.id} ${family.label || ''}`)
    return terms.every(term => text.includes(term))
  })
}
