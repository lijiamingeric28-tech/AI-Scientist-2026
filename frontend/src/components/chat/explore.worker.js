import { exploreCurve } from './exploreMath'

self.onmessage = ({ data }) => {
  try {
    self.postMessage({ id: data.id, ...exploreCurve(data) })
  } catch (error) {
    self.postMessage({ id: data.id, error: error.message })
  }
}
