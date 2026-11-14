// Format declared values only. No interpretation, conversion, or averaging.
export function typedValueText(value) {
  if(value==null)return '未记录'
  if(value.kind==='interval') {
    const bounds=`${value.lower??'−∞'}, ${value.upper??'+∞'}`
    return typeof value.lower_closed==='boolean'&&typeof value.upper_closed==='boolean'
      ? `${value.lower_closed?'[':'('}${bounds}${value.upper_closed?']':')'}`
      : `${bounds}（边界开闭未记录）`
  }
  if(value.kind==='boolean')return value.value===true?'是':value.value===false?'否':'未记录'
  if(value.kind==='category')return value.raw_label??value.code??'未记录'
  if(value.kind==='relation')return value.other_entity?.raw_name??'关系对象未记录'
  return String(value.value??'未记录')
}
export function limitedValueText(value,limit) {
  return `${limit==='upper'?'上限 ':limit==='lower'?'下限 ':''}${typedValueText(value)}`
}
