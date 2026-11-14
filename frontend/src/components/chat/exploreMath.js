import { parse } from 'mathjs'

const operators = new Set(['add', 'subtract', 'multiply', 'divide', 'pow', 'mod', 'unaryMinus', 'unaryPlus'])
const functions = new Set(['sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'sqrt', 'log', 'log10', 'exp', 'abs', 'min', 'max'])
const constants = new Set(['pi', 'e'])

export function exploreCurve({ expression, x, parameters, values }) {
  if (typeof expression !== 'string' || expression.length > 350) throw new Error('公式超出可试算范围')
  const tree = parse(expression)
  const names = new Set(parameters.map(p => p.name))
  const scope = new Map()
  for (const param of parameters) {
    const value = values[param.name] ?? param.value
    if (!Number.isFinite(value) || value < param.min || value > param.max) throw new Error('参数超出范围')
    scope.set(param.name, value)
  }
  const axis = parameters.find(p => p.name === x)
  if (!axis) throw new Error('找不到横轴参数')
  let count = 0
  function inspect(node) {
    if (++count > 150) throw new Error('公式超出可试算范围')
    if (node.isConstantNode && typeof node.value === 'number' && Number.isFinite(node.value)) return
    if (node.isSymbolNode && (names.has(node.name) || constants.has(node.name))) return
    if (node.isOperatorNode && operators.has(node.fn)) return node.args.forEach(inspect)
    if (node.isParenthesisNode) return inspect(node.content)
    if (node.isFunctionNode && node.fn.isSymbolNode && functions.has(node.fn.name)) return node.args.forEach(inspect)
    throw new Error('公式包含未支持的运算')
  }
  inspect(tree)
  const compiled = tree.compile()
  const compute = () => {
    const result = compiled.evaluate(scope)
    return typeof result === 'number' && Number.isFinite(result) ? result : null
  }
  const current = compute()
  const xValue = scope.get(x)
  const samples = axis.choices.length ? [...axis.choices].sort((a, b) => a - b) :
    Array.from({ length: 101 }, (_, i) => axis.min + (axis.max - axis.min) * i / 100)
  const points = samples.map(value => {
    scope.set(x, value)
    return [value, compute()]
  })
  return { current, xValue, points }
}
