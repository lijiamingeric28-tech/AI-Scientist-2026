// Pure policies shared by the native driver and its offline checks.
export function createReviewPacing(){
 const seen=new Set()
 return {
  get count(){return seen.size},
  claim(key){
   if(!key)throw Error('Missing historical review identity')
   if(seen.has(key))return null
   const first=seen.size===0
   seen.add(key)
   return {first,readSeconds:first?8:.25,choiceSeconds:first?2:0}
  }
 }
}
export function needsNavigation({current,selected,pressed,active,returnToDirectory=false}={}){
 return returnToDirectory||!(current==='page'||current==='true'||selected==='true'||pressed==='true'||active)
}
export function pointerMotion(from,to){
 const distance=Math.hypot(to.x-from.x,to.y-from.y),count=Math.max(12,Math.min(26,Math.ceil(distance/35)))
 return Array.from({length:count},(_,i)=>{
  const t=(i+1)/count,ease=t*t*(3-2*t)
  return {x:from.x+(to.x-from.x)*ease,y:from.y+(to.y-from.y)*ease}
 })
}
