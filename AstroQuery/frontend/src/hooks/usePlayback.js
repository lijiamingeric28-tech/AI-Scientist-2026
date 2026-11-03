import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getReplayClock } from '@/services/api'
import { buildTrack, lastAt, nextPlayback } from '@/lib/replayTrack'

export function usePlayback(request) {
  const taskId = request?.taskId
  const [data, setData] = useState(null)
  const [position, setPosition] = useState({elapsed: 0, seq: 0})
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(10)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [seekRevision, setSeekRevision] = useState(0)
  const [painted, setPainted] = useState(null)
  const [released, setReleased] = useState(new Set())
  const acknowledged = useRef(null)
  const track = useMemo(() => buildTrack(data?.taskId === taskId ? data : null), [data, taskId])
  const ready = data?.taskId === taskId
  const positionRef = useRef(position)
  positionRef.current = position
  const isImportant = track.stops.some(s => s.seq === position.seq) || position.seq === 0
  const gate = track.gates.find(g => g.available && !released.has(g.key) &&
    position.seq >= g.question_seq && position.seq < g.answer_seq)
  const lastSeq = track.events.at(-1)?.seq || 0

  const shown = useCallback((id, seq) => {
    if (id !== taskId || acknowledged.current?.seq === seq && acknowledged.current?.id === id) return
    acknowledged.current = {id, seq, at: performance.now()}
    setPainted(seq)
  }, [taskId])

  useEffect(() => {
    setData(null); setPosition({elapsed: 0, seq: 0}); setPlaying(false)
    setError(''); setPainted(null); setReleased(new Set()); acknowledged.current = null
    if (!taskId) return
    const controller = new AbortController()
    getReplayClock(taskId, {signal: controller.signal}).then(result => {
      if (controller.signal.aborted) return
      setSpeed(request.speed || 10); setData({...result, taskId}); setPlaying(true)
    }).catch(e => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [taskId, retry])

  useEffect(() => {
    if (!ready || !playing || gate) return
    let prior = performance.now()
    const timer = setInterval(() => {
      const now = performance.now(), delta = (now - prior) / 1000
      prior = now
      const current = positionRef.current
      if (isImportant && (acknowledged.current?.id !== taskId || acknowledged.current?.seq !== current.seq)) return
      if (current.seq >= lastSeq && current.elapsed >= track.duration) { setPlaying(false); return }
      if (isImportant && now - acknowledged.current.at < 550) return
      setPosition(nextPlayback(track, current, delta * speed, released))
    }, 160)
    return () => clearInterval(timer)
  }, [ready, playing, speed, track, taskId, isImportant, lastSeq, gate, released])

  const seek = seconds => {
    const elapsed = Math.max(0, Math.min(track.duration, seconds))
    const seq = lastAt(track.events, elapsed)?.seq || 0
    setReleased(previous => new Set([...previous].filter(key =>
      (track.gates.find(g => g.key === key)?.answer_seq ?? Infinity) <= seq)))
    setSeekRevision(v => v + 1); setPosition({elapsed, seq}); acknowledged.current = null
  }
  const seekEvent = seq => {
    const event = track.events.find(e => e.seq === seq)
    if (!event) return
    seek(event.t)
    setPosition({elapsed: event.t, seq: event.seq})
  }
  const replay = () => { setReleased(new Set()); seek(0); setPlaying(true) }
  const submitGate = key => {
    if (!gate || gate.key !== key) return
    setReleased(previous => new Set([...previous, key]))
    setPlaying(true)
  }
  return request ? {
    taskId, ...position, duration: track.duration, start: track.start, playing, speed,
    error, ready, milestones: data?.milestones || [], seekRevision, shown, gate,
    gates: track.gates, submitGate, seek, seekEvent, replay, setSpeed,
    retry: () => setRetry(v => v + 1),
    finished: ready && position.seq >= lastSeq && painted === position.seq,
    setPlaying: value => {
      if (value && position.seq >= lastSeq && position.elapsed >= track.duration) replay()
      else setPlaying(value)
    },
  } : null
}
