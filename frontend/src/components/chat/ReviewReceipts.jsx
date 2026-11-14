import { reviewReceipt } from '@/lib/reviewReceipt'
import ReviewReading from './ReviewReading'

export default function ReviewReceipts({ reviews = [], lifecycle }) {
  const rows = reviews.map(review => ({ review, receipt: reviewReceipt(review, lifecycle) })).filter(row => row.receipt)
  if (!rows.length) return null
  return <section aria-label="已保存的审核与复检" className="review-history">
    <h3>审核记录</h3>
    {rows.map(({ review, receipt }) => <details key={review.review_id} open={receipt.outcome.includes('未决')} style={{ padding: '8px 0' }}>
      <summary>{receipt.status}：{receipt.answer}</summary>
      {receipt.simulation && <p className="hint">模拟审核</p>}
      {receipt.reason && <p>回答依据：{receipt.reason}</p>}
      {receipt.outcome && <p>{receipt.outcome}</p>}
      <ReviewReading review={review} taskId={review.task_id}/>
    </details>)}
  </section>
}
