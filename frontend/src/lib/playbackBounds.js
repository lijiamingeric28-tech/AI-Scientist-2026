// Playback uses the saved task terminal, not later export/download events.
export function playbackBounds(data) {
  const events=data?.timeline||[]
  const start=Date.parse(data?.created_at||events[0]?.at||'')
  const end=Date.parse(data?.terminal_at||events.at(-1)?.at||'')
  return {start:Number.isFinite(start)?start:0,duration:Number.isFinite(start)&&Number.isFinite(end)?Math.max(0,(end-start)/1000):0}
}
