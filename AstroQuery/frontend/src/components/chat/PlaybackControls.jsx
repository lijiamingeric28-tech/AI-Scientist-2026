import { Button } from '@/components/ui/button'
const time=n=>`${Math.floor(Math.round(n)/60)}:${String(Math.round(n)%60).padStart(2,'0')}`
export default function PlaybackControls({player,onExit,onFinal}) {
 return <section className="player-toolbar" aria-label="只读播放器"><Button variant="outline" onClick={onExit}>返回来处</Button><strong>只读回放</strong>
  <Button disabled={!player.ready} onClick={()=>player.setPlaying(!player.playing)}>{player.playing?'暂停播放':player.finished?'再次播放':'播放'}</Button><Button variant="ghost" disabled={!player.ready} onClick={player.replay}>重播</Button>
  <select aria-label="播放速度" disabled={!player.ready} value={player.speed} onChange={e=>player.setSpeed(Number(e.target.value))}>{[.25,.5,1,2,5,10,20,50,100].map(s=><option key={s} value={s}>{s}倍</option>)}</select>
  <span className="player-time">{time(player.elapsed)} / {time(player.duration)}{player.ready&&` · ${new Date(player.start+player.elapsed*1000).toLocaleTimeString('zh-CN',{hour12:false})}`}</span>
  <input type="range" aria-label="原任务时间轴" aria-valuetext={time(player.elapsed)} disabled={!player.ready || !player.duration} min="0" max={player.duration||1} step=".001" value={player.elapsed} onChange={e=>player.seek(Number(e.target.value))}
    onKeyDown={e=>{const offsets={ArrowLeft:-5,ArrowDown:-5,ArrowRight:5,ArrowUp:5,PageDown:-60,PageUp:60};if(e.key in offsets || e.key==='Home' || e.key==='End'){e.preventDefault();player.seek(e.key==='Home'?0:e.key==='End'?player.duration:player.elapsed+offsets[e.key])}}}/>
  <select className="player-stage-menu" aria-label="跳到阶段" disabled={!player.ready} value="" onChange={e=>player.seekEvent(Number(e.target.value))}><option value="">跳到阶段或回访</option>{player.milestones.map((m,i)=><option key={m.seq} value={m.seq}>{i+1}. {({retrieval:'数据检索',extraction:'数据提取',quality_check:'质量检查',clean:'数据清洗',comparison:'数据对照',deliver:'数据交付',insight:'数据洞察'})[m.stage_id]||m.stage_id} · {new Date(m.at).toLocaleTimeString('zh-CN',{hour12:false})}</option>)}</select>
  <button className="text-link" onClick={onFinal}>查看原任务最终结果</button>{player.finished&&<span>回放结束</span>}{player.error&&<p role="alert">{player.error} <button onClick={player.retry}>重新载入</button></p>}
 </section>
}
