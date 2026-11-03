import test from 'node:test'
import assert from 'node:assert/strict'
import { plotNumber, errorEndpoint, plotBounds } from '../src/lib/numericPlot.js'

test('decimal chart must not collapse underflow, long identifiers or tiny errors into zero', () => {
  assert.equal(plotNumber('1e-350'), null)
  assert.equal(plotNumber('1234567890123456789'), null)
  assert.equal(plotNumber('1e350'), null)
  assert.equal(plotNumber('0.000'), 0)
  assert.equal(plotNumber('-1.23000'), -1.23)
  assert.equal(plotNumber('1e-12'), 1e-12)
  assert.equal(errorEndpoint(1, '1e-20', 1), null)
  assert.equal(errorEndpoint(1, '0.1', -1), .9)
})

test('large plot bound scan avoids argument spreading and empty axes', () => {
  const points = Array.from({ length: 200000 }, (_, centre) => ({ centre, ranges: [] }))
  assert.deepEqual(plotBounds(points), { lo: 0, hi: 199999, span: 199999, valid: true })
  assert.equal(plotBounds([]).valid, false)
})
