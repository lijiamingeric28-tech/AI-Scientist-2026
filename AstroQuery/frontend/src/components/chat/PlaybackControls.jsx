import { Icon } from '@/components/icons'
import './chatStage.css'

const time = (n) => `${Math.floor(Math.round(n) / 60)}:${String(Math.round(n) % 60).padStart(2, '0')}`

const stageLabels = {
  retrieval: '数据检索',
  extraction: '数据提取',
  quality_check: '质量检查',
  clean: '数据清洗',
  comparison: '数据对照',
  deliver: '数据交付',
  insight: '数据洞察',
}

export default function PlaybackControls({ player, onExit, onFinal }) {
  const pct = player.duration > 0 ? Math.min(100, Math.max(0, (player.elapsed / player.duration) * 100)) : 0
  return (
    <section className="player-toolbar modern-player-toolbar" aria-label="只读播放器">
      <div className="player-toolbar-left">
        <button type="button" className="player-btn-back" onClick={onExit}>
          <Icon.ArrowLeft style={{ width: 13, height: 13 }} aria-hidden="true" />
          <span>返回</span>
        </button>
        <span className="player-badge">只读回放</span>
      </div>

      <div className="player-toolbar-center">
        <button
          type="button"
          className="player-play-btn"
          disabled={!player.ready}
          onClick={() => player.setPlaying(!player.playing)}
          title={player.playing ? '暂停播放' : player.finished ? '再次播放' : '播放'}
        >
          {player.playing ? (
            <Icon.Pause style={{ width: 14, height: 14 }} aria-hidden="true" />
          ) : (
            <Icon.Play style={{ width: 14, height: 14 }} aria-hidden="true" />
          )}
          <span>{player.playing ? '暂停' : player.finished ? '再次播放' : '播放'}</span>
        </button>

        <button
          type="button"
          className="player-btn-secondary"
          disabled={!player.ready}
          onClick={player.replay}
          title="重播"
        >
          <Icon.RotateCcw style={{ width: 13, height: 13 }} aria-hidden="true" />
          <span>重播</span>
        </button>

        <select
          className="player-select-speed font-mono"
          aria-label="播放速度"
          disabled={!player.ready}
          value={player.speed}
          onChange={(e) => player.setSpeed(Number(e.target.value))}
        >
          {[0.25, 0.5, 1, 2, 5, 10, 20, 50, 100].map((s) => (
            <option key={s} value={s}>
              {s}倍
            </option>
          ))}
        </select>

        <span className="player-time-badge font-mono">
          {time(player.elapsed)} / {time(player.duration)}
          {player.ready && ` · ${new Date(player.start + player.elapsed * 1000).toLocaleTimeString('zh-CN', { hour12: false })}`}
        </span>
      </div>

      <div className="player-slider-container">
        <input
          type="range"
          className="player-range-slider"
          style={{
            background: `linear-gradient(to right, var(--accent, #44785b) 0%, var(--accent, #44785b) ${pct}%, var(--surface-border, #dce4df) ${pct}%, var(--surface-border, #dce4df) 100%)`
          }}
          aria-label="原任务时间轴"
          aria-valuetext={time(player.elapsed)}
          disabled={!player.ready || !player.duration}
          min="0"
          max={player.duration || 1}
          step="0.001"
          value={player.elapsed}
          onChange={(e) => player.seek(Number(e.target.value))}
          onKeyDown={(e) => {
            const offsets = { ArrowLeft: -5, ArrowDown: -5, ArrowRight: 5, ArrowUp: 5, PageDown: -60, PageUp: 60 }
            if (e.key in offsets || e.key === 'Home' || e.key === 'End') {
              e.preventDefault()
              player.seek(e.key === 'Home' ? 0 : e.key === 'End' ? player.duration : player.elapsed + offsets[e.key])
            }
          }}
        />
      </div>

      <div className="player-toolbar-right">
        <select
          className="player-stage-menu font-mono"
          aria-label="跳到阶段"
          disabled={!player.ready}
          value=""
          onChange={(e) => player.seekEvent(Number(e.target.value))}
        >
          <option value="">跳到阶段或回访…</option>
          {player.milestones.map((m, i) => (
            <option key={m.seq} value={m.seq}>
              {i + 1}. {stageLabels[m.stage_id] || m.stage_id} · {new Date(m.at).toLocaleTimeString('zh-CN', { hour12: false })}
            </option>
          ))}
        </select>

        <button type="button" className="text-link player-link-final" onClick={onFinal}>
          查看最终结果
        </button>
      </div>
    </section>
  )
}
