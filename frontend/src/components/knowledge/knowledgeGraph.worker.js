import { layoutKnowledgeGraph } from '../../lib/knowledgeGraph'

self.onmessage = ({ data }) => {
  const { sequence, nodes, edges, focusId } = data
  self.postMessage({ sequence, nodes: layoutKnowledgeGraph(nodes, edges, { focusId }) })
}
