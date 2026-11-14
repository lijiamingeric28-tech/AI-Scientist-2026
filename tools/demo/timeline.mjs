export const stamp=seconds=>{
 const ms=Math.round(seconds*1000)
 return `${String(Math.floor(ms/3600000)).padStart(2,'0')}:${String(Math.floor(ms/60000)%60).padStart(2,'0')}:${String(Math.floor(ms/1000)%60).padStart(2,'0')},${String(ms%1000).padStart(3,'0')}`
}
export function subtitles(shots,field='seconds') {
 let time=0
 return shots.map((s,i)=>{const start=time;time+=s[field];return `${i+1}\n${stamp(start)} --> ${stamp(time)}\n${s.caption}\n`}).join('\n')
}
