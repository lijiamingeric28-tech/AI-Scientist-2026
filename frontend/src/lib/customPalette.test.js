import test from 'node:test'
import assert from 'node:assert/strict'
import {
  PALETTE_PRESETS,
  DEFAULT_PALETTE,
  isValidHexColor,
  normalizeHex,
  loadSavedPalette,
  savePalette,
  resetPaletteToDefault,
} from './customPalette.js'

test('customPalette presets define all 5 required seed colors with valid hex format', () => {
  assert.equal(PALETTE_PRESETS.length, 5)
  for (const preset of PALETTE_PRESETS) {
    assert.ok(preset.id)
    assert.ok(preset.name)
    const { accent, bg, surface, ink, aux } = preset.colors
    assert.ok(isValidHexColor(accent), `Accent ${accent} in ${preset.id} is valid hex`)
    assert.ok(isValidHexColor(bg), `Bg ${bg} in ${preset.id} is valid hex`)
    assert.ok(isValidHexColor(surface), `Surface ${surface} in ${preset.id} is valid hex`)
    assert.ok(isValidHexColor(ink), `Ink ${ink} in ${preset.id} is valid hex`)
    assert.ok(isValidHexColor(aux), `Aux ${aux} in ${preset.id} is valid hex`)
  }
})

test('isValidHexColor validates 3 and 6 char hex codes', () => {
  assert.equal(isValidHexColor('#fff'), true)
  assert.equal(isValidHexColor('#24583b'), true)
  assert.equal(isValidHexColor('#24583B'), true)
  assert.equal(isValidHexColor('24583b'), false)
  assert.equal(isValidHexColor('#ffff'), false)
  assert.equal(isValidHexColor('rgb(0,0,0)'), false)
})

test('normalizeHex standardizes hex strings', () => {
  assert.equal(normalizeHex('#fff'), '#ffffff')
  assert.equal(normalizeHex('#24583B'), '#24583b')
  assert.equal(normalizeHex('24583b'), '#24583b')
})
