export function backToTopPosition(bounds,viewport,button,point) {
  const minX=Math.max(0,bounds.left)+12,minY=Math.max(0,bounds.top)+12
  const maxX=Math.max(minX,Math.min(viewport.width,bounds.right)-button.width-12)
  const maxY=Math.max(minY,Math.min(viewport.height,bounds.bottom)-button.height-12)
  return {x:Math.max(minX,Math.min(maxX,point?.x??maxX)),y:Math.max(minY,Math.min(maxY,point?.y??maxY))}
}
