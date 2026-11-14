export function readAnswerChartTheme(style) {
  return { ink:style.getPropertyValue('color').trim(), paper:style.getPropertyValue('background-color').trim(),
    line:style.getPropertyValue('border-top-color').trim(), accent:style.getPropertyValue('outline-color').trim(),
    font:style.getPropertyValue('font-family').trim() }
}
