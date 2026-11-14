export const REPLAY_SPEED_KEY = 'astro_replay_speed'

export function loadReplaySpeed() {
  try { const n = Number(localStorage.getItem(REPLAY_SPEED_KEY)); return Number.isFinite(n) && n >= 0.25 && n <= 100 ? n : 10 } catch { return 10 }
}

export function saveReplaySpeed(value) {
  try { localStorage.setItem(REPLAY_SPEED_KEY, String(Math.max(0.25, Math.min(100, value)))) } catch { /* preferences only */ }
}
