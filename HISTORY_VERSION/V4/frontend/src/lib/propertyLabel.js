import labels from '../data/propertyLabels.json' with { type: 'json' }
import { createContext, createElement, useContext, useMemo } from 'react'
export const propertyLabel = field => labels[field] || field || '未标识性质'
export function createPropertyLabel(properties = []) {
  const taskNames = new Map(properties.filter(p => p && typeof (p.propertyId || p.property_id) === 'string' && typeof (p.name || p.name_cn) === 'string').map(p => [p.propertyId || p.property_id, p.name || p.name_cn]))
  return field => taskNames.get(field) || propertyLabel(field)
}
const PropertyNames = createContext(propertyLabel)
export function PropertyNamesProvider({ properties, children }) {
  const label = useMemo(() => createPropertyLabel(properties || []), [properties])
  return createElement(PropertyNames.Provider, { value: label }, children)
}
export const usePropertyLabel = () => useContext(PropertyNames)
