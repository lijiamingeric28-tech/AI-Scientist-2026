import test from 'node:test'
import assert from 'node:assert/strict'
import {playbackBounds} from './playbackBounds.js'
test('playback stops at original terminal even when exports occur hours later',()=>{
  const b=playbackBounds({created_at:'2026-11-02T00:10:11.231Z',terminal_at:'2026-11-02T00:54:33.981Z',timeline:[{at:'2026-11-02T06:00:00Z'}]})
  assert.equal(b.duration,2662.75)
})
test('legacy playback uses actual event timestamps and empty history has no duration',()=>{
  assert.equal(playbackBounds({timeline:[{at:'2026-11-02T00:00:00Z'},{at:'2026-11-02T00:01:00Z'}]}).duration,60)
  assert.deepEqual(playbackBounds(null),{start:0,duration:0})
})
