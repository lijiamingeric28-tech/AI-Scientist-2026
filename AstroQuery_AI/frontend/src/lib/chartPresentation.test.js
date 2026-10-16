import test from 'node:test'
import assert from 'node:assert/strict'
import { measurementAxis, axisLabel, axisTickLabels, resolveSelection, relationshipKeys } from './chartPresentation.js'
test('display ticks cover zero, negative, single-value and extreme domains', () => {
  for (const [min, max] of [[0, 0], [-12, 8], [5.58, 5.58], [1e-12, 2e-12], [1e12, 3e12], [-1e308, 1e308]]) {
    const axis = measurementAxis(min, max)
    assert.ok(axis.lo <= min && axis.hi >= max)
    assert.ok(axis.ticks.length >= 2 && axis.ticks.length <= 12)
    assert.ok(axis.ticks.every(Number.isFinite))
    assert.ok(axis.ticks.every((v, i, all) => !i || v > all[i - 1]))
    assert.equal(new Set(axis.ticks.map(axisLabel)).size, axis.ticks.length)
  }
  assert.equal(axisLabel(0), '0')
  assert.equal(measurementAxis(NaN, 1), null)
  const tight = measurementAxis(5.580000001, 5.580000003)
  assert.equal(new Set(axisTickLabels(tight.ticks)).size, tight.ticks.length)
})
test('relationship selection survives reordered reports and preserves duplicate entries', () => {
  const a = {field_a:'distance',field_b:'parallax'}, b = {field_a:'age',field_b:'metallicity'}
  const keys = relationshipKeys([a,b])
  assert.equal(resolveSelection(keys[1],relationshipKeys([b,a])),keys[1])
  assert.equal(resolveSelection('removed',keys),keys[0])
  assert.equal(resolveSelection(keys[0],[]),null)
  assert.equal(new Set(relationshipKeys([a,a])).size,2)
})
