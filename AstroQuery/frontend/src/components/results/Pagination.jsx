import { Button } from '@/components/ui/button'
import { usePageTransition } from '@/hooks/usePageTransition'

export default function Pagination({ total, page, onPage, size = 20 }) {
  const pages = Math.max(1, Math.ceil(total / size)), current = Math.min(page, pages)
  const feedback = usePageTransition()
  const turn = (event, next) => feedback(event.currentTarget.closest('[data-page-region]'), () => onPage(next))
  return <div className="pagination-row"><span>{total} 项 · 每页 {size} 项</span><div><Button variant="outline" size="sm" disabled={current === 1} onClick={event => turn(event, current - 1)}>上一页</Button><span>{current} / {pages}</span><Button variant="outline" size="sm" disabled={current === pages} onClick={event => turn(event, current + 1)}>下一页</Button></div></div>
}
