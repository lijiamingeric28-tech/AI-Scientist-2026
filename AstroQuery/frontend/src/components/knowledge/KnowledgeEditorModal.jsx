import React, { useState, useEffect, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { LatexMath } from '@/components/results/LatexMath'
import { KNOWLEDGE_CATEGORIES, isValidFormula } from './knowledgeConstants'

export default function KnowledgeEditorModal({
  isOpen,
  initialData,
  mode = 'create',
  existingCategories = [],
  onSave,
  onClose,
}) {
  if (!isOpen) return null

  const isFork = mode === 'fork'
  const isEdit = mode === 'edit'
  const isOverrideBase = isEdit && initialData && initialData.is_user === false

  const [title, setTitle] = useState('')
  const [category, setCategory] = useState('user_private')
  const [isCustomCategory, setIsCustomCategory] = useState(false)
  const [customCategoryName, setCustomCategoryName] = useState('')
  const [formula, setFormula] = useState('')
  const [description, setDescription] = useState('')
  const [conditionsText, setConditionsText] = useState('')
  const [propertiesText, setPropertiesText] = useState('')
  const [tagsText, setTagsText] = useState('')
  const [sources, setSources] = useState('')
  const [preferred, setPreferred] = useState(false)
  const [paramsList, setParamsList] = useState([
    { name: '', symbol: '', range: '', unit: '', desc: '' },
  ])
  const [errorMsg, setErrorMsg] = useState('')

  // Build combined available category list
  const availableCategories = useMemo(() => {
    const list = [...KNOWLEDGE_CATEGORIES.filter(c => c.id !== 'all')]
    const ids = new Set(list.map(c => c.id))
    for (const c of existingCategories) {
      if (c.id && c.id !== 'all' && !ids.has(c.id)) {
        ids.add(c.id)
        list.push({ id: c.id, label: c.label || c.id, is_custom: true })
      }
    }
    return list
  }, [existingCategories])

  useEffect(() => {
    if (initialData) {
      setTitle(
        isFork
          ? `${initialData.title || initialData.name || ''} (派生版)`
          : initialData.title || initialData.name || ''
      )
      const rawCat = initialData.category || 'physical_laws'
      const matched = availableCategories.some(c => c.id === rawCat || c.label === rawCat)
      if (matched) {
        setCategory(rawCat)
        setIsCustomCategory(false)
        setCustomCategoryName('')
      } else {
        setCategory('__custom__')
        setIsCustomCategory(true)
        setCustomCategoryName(rawCat)
      }

      setFormula(initialData.formula || initialData.claim?.formula || '')
      setDescription(initialData.description || initialData.claim?.text || initialData.content || '')
      setConditionsText(Array.isArray(initialData.conditions) ? initialData.conditions.join('\n') : (initialData.conditions || ''))
      setPropertiesText(Array.isArray(initialData.properties) ? initialData.properties.join(', ') : (initialData.properties || ''))
      setTagsText(Array.isArray(initialData.tags) ? initialData.tags.join(', ') : (initialData.tags || ''))
      setSources(typeof initialData.sources === 'string' ? initialData.sources : initialData.sources?.[0]?.title || initialData.source || '')
      setPreferred(Boolean(initialData.user_preference === 'preferred' || initialData.preferred))
      if (Array.isArray(initialData.parameters) && initialData.parameters.length > 0) {
        setParamsList(initialData.parameters.map(p => ({
          name: p.name || '',
          symbol: p.symbol || '',
          range: p.range || '',
          unit: p.unit || '',
          desc: p.desc || p.description || '',
        })))
      } else {
        setParamsList([{ name: '', symbol: '', range: '', unit: '', desc: '' }])
      }
    } else {
      setTitle('')
      setCategory(availableCategories[0]?.id || 'physical_laws')
      setIsCustomCategory(false)
      setCustomCategoryName('')
      setFormula('')
      setDescription('')
      setConditionsText('')
      setPropertiesText('')
      setTagsText('')
      setSources('')
      setPreferred(false)
      setParamsList([{ name: '', symbol: '', range: '', unit: '', desc: '' }])
    }
    setErrorMsg('')
  }, [initialData, isFork, isOpen, availableCategories])

  const handleAddParam = () => {
    setParamsList(prev => [...prev, { name: '', symbol: '', range: '', unit: '', desc: '' }])
  }

  const handleRemoveParam = (index) => {
    setParamsList(prev => prev.filter((_, i) => i !== index))
  }

  const handleParamChange = (index, field, value) => {
    setParamsList(prev => {
      const copy = [...prev]
      copy[index] = { ...copy[index], [field]: value }
      return copy
    })
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!title.trim()) {
      setErrorMsg('请填写理论知识标题')
      return
    }

    const finalCategory = isCustomCategory
      ? (customCategoryName.trim() || '用户自定义分类')
      : category

    const cleanedParams = paramsList.filter(p => p.name.trim() || p.symbol.trim() || p.range.trim())
    const conditions = conditionsText
      .split('\n')
      .map(s => s.trim())
      .filter(Boolean)
    const properties = propertiesText
      .split(/[,，]/)
      .map(s => s.trim())
      .filter(Boolean)
    const tags = tagsText
      .split(/[,，]/)
      .map(s => s.trim())
      .filter(Boolean)

    const payload = {
      ...(initialData && !isFork ? { id: initialData.id } : { id: `user_${Date.now()}` }),
      title: title.trim(),
      category: finalCategory,
      formula: formula.trim(),
      description: description.trim(),
      conditions,
      parameters: cleanedParams,
      properties,
      tags,
      sources: sources.trim(),
      preferred,
      user_preference: preferred ? 'preferred' : 'neutral',
      is_user: true,
      ...(isOverrideBase ? { is_override: true, base_id: initialData.id } : {}),
      ...(isFork ? { base_id: initialData?.id } : {}),
      updated_at: new Date().toISOString(),
    }

    onSave(payload, isFork ? 'fork' : isEdit ? 'edit' : 'create')
  }

  return (
    <div className="kw-modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="kw-modal-dialog" onClick={e => e.stopPropagation()}>
        <header className="kw-modal-header">
          <h3>
            <Icon.Edit style={{ width: 18, height: 18, color: 'var(--accent)' }} />
            <span>
              {isFork
                ? '派生自已有理论知识'
                : isEdit
                ? isOverrideBase
                  ? '修改系统内置理论 (保存为用户覆盖版)'
                  : '编辑理论知识'
                : '新增理论知识'}
            </span>
          </h3>
          <button
            type="button"
            className="kw-icon-btn"
            onClick={onClose}
            aria-label="关闭"
          >
            <Icon.Close style={{ width: 16, height: 16 }} />
          </button>
        </header>

        <form onSubmit={handleSubmit} className="kw-modal-body">
          {errorMsg && (
            <div className="app-notice error" role="alert">
              {errorMsg}
            </div>
          )}

          {isOverrideBase && (
            <div
              style={{
                padding: '8px 12px',
                background: 'rgba(59, 130, 246, 0.08)',
                border: '1px solid rgba(59, 130, 246, 0.25)',
                borderRadius: 6,
                fontSize: 12.5,
                color: 'var(--content-fg)',
                lineHeight: 1.5,
              }}
            >
              您正在编辑系统预置理论。保存后将作为您的专属增量覆盖层生效，随时可通过详情侧边栏中的「恢复默认」一键还原出厂设置。
            </div>
          )}

          <div className="kw-form-group">
            <label className="kw-form-label">
              <span>理论名称与定律标题</span>
              <span className="kw-form-hint">必填</span>
            </label>
            <input
              type="text"
              className="kw-input"
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="例如：斯特藩-玻尔兹曼定律 / 修正光度极限模型"
              autoFocus
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {/* Category selection with custom category support */}
            <div className="kw-form-group">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                <label className="kw-form-label" style={{ margin: 0 }}>
                  <span>知识分类</span>
                </label>
                <button
                  type="button"
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--accent)',
                    fontSize: 12,
                    cursor: 'pointer',
                    padding: 0,
                  }}
                  onClick={() => setIsCustomCategory(prev => !prev)}
                >
                  {isCustomCategory ? '← 选择已有分类' : '+ 新增自定义分类'}
                </button>
              </div>

              {isCustomCategory ? (
                <input
                  type="text"
                  className="kw-input"
                  value={customCategoryName}
                  onChange={e => setCustomCategoryName(e.target.value)}
                  placeholder="输入自定义新分类名称 (如：引力波天文学)"
                  autoFocus
                />
              ) : (
                <select
                  className="kw-select"
                  value={category}
                  onChange={e => {
                    if (e.target.value === '__custom__') {
                      setIsCustomCategory(true)
                    } else {
                      setCategory(e.target.value)
                    }
                  }}
                >
                  {availableCategories.map(c => (
                    <option key={c.id} value={c.id}>
                      {c.label} {c.is_custom ? '(自定义)' : ''}
                    </option>
                  ))}
                  <option value="__custom__">+ 新增自定义分类…</option>
                </select>
              )}
            </div>

            <div className="kw-form-group">
              <label className="kw-form-label">
                <span>科研优先标记</span>
              </label>
              <button
                type="button"
                className={`kw-filter-pref-btn ${preferred ? 'active' : ''}`}
                style={{ height: 38, justifyContent: 'center' }}
                onClick={() => setPreferred(p => !p)}
              >
                {preferred ? <Icon.StarFilled style={{ width: 14, height: 14 }} /> : <Icon.Star style={{ width: 14, height: 14 }} />}
                <span>{preferred ? '已设为科研优先理论' : '设为科研优先理论'}</span>
              </button>
            </div>
          </div>

          <div className="kw-form-group">
            <label className="kw-form-label">
              <span>LaTeX 科学公式与数学表达式</span>
              <span className="kw-form-hint">支持标准 KaTeX 语法（纯理论描述请在下方阐述填写）</span>
            </label>
            <input
              type="text"
              className="kw-input"
              value={formula}
              onChange={e => setFormula(e.target.value)}
              placeholder="例如：L = 4\pi R^2 \sigma T_{\text{eff}}^4"
            />
            {formula.trim() && (
              <div style={{ marginTop: 8 }}>
                <span style={{ fontSize: 11, color: 'var(--content-fg-secondary)', marginBottom: 4, display: 'block' }}>实时渲染预览：</span>
                <div className="kw-latex-preview-card">
                  {isValidFormula(formula) ? (
                    <LatexMath math={formula} displayMode />
                  ) : (
                    <span style={{ fontSize: 12, color: 'var(--content-fg-secondary)' }}>
                      （提示：输入内容将被作为文本解析）
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="kw-form-group">
            <label className="kw-form-label">
              <span>核心理论机制阐述</span>
            </label>
            <textarea
              className="kw-textarea"
              rows={3}
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="阐述该理论在天体物理中的物理意义、适用边界与观测验证意义…"
            />
          </div>

          <div className="kw-form-group">
            <label className="kw-form-label">
              <span>适用物理条件与边界假定</span>
              <span className="kw-form-hint">每行一条</span>
            </label>
            <textarea
              className="kw-textarea"
              rows={2}
              value={conditionsText}
              onChange={e => setConditionsText(e.target.value)}
              placeholder="局域热动平衡(LTE)&#10;极端相对论费米气体&#10;消光比值 R_V = 3.1"
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div className="kw-form-group">
              <label className="kw-form-label">
                <span>关联物理量</span>
                <span className="kw-form-hint">逗号分隔</span>
              </label>
              <input
                type="text"
                className="kw-input"
                value={propertiesText}
                onChange={e => setPropertiesText(e.target.value)}
                placeholder="例如：luminosity, teff, radius"
              />
            </div>

            <div className="kw-form-group">
              <label className="kw-form-label">
                <span>领域学术标签 (Tags)</span>
                <span className="kw-form-hint">逗号分隔</span>
              </label>
              <input
                type="text"
                className="kw-input"
                value={tagsText}
                onChange={e => setTagsText(e.target.value)}
                placeholder="例如：恒星物理, 热辐射, 黑体"
              />
            </div>
          </div>

          <div className="kw-form-group">
            <label className="kw-form-label">
              <span>参考文献与权威来源</span>
            </label>
            <input
              type="text"
              className="kw-input"
              value={sources}
              onChange={e => setSources(e.target.value)}
              placeholder="例如：Carroll & Ostlie (2017) §3.2 / Gaia DR3 Documentation"
            />
          </div>

          {/* Theoretical Parameters Configuration Table */}
          <div className="kw-form-group">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <label className="kw-form-label" style={{ margin: 0 }}>
                <span>关键特征参数表</span>
              </label>
              <Button type="button" variant="ghost" size="sm" onClick={handleAddParam}>
                <Icon.Plus style={{ width: 12, height: 12 }} />
                <span>添加参数</span>
              </Button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {paramsList.map((param, index) => (
                <div key={index} style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr 1.2fr 0.8fr 2fr 30px', gap: 6, alignItems: 'center' }}>
                  <input
                    type="text"
                    className="kw-input"
                    placeholder="参数名"
                    value={param.name}
                    onChange={e => handleParamChange(index, 'name', e.target.value)}
                  />
                  <input
                    type="text"
                    className="kw-input"
                    placeholder="符号"
                    value={param.symbol}
                    onChange={e => handleParamChange(index, 'symbol', e.target.value)}
                  />
                  <input
                    type="text"
                    className="kw-input"
                    placeholder="取值范围"
                    value={param.range}
                    onChange={e => handleParamChange(index, 'range', e.target.value)}
                  />
                  <input
                    type="text"
                    className="kw-input"
                    placeholder="单位"
                    value={param.unit}
                    onChange={e => handleParamChange(index, 'unit', e.target.value)}
                  />
                  <input
                    type="text"
                    className="kw-input"
                    placeholder="物理说明"
                    value={param.desc}
                    onChange={e => handleParamChange(index, 'desc', e.target.value)}
                  />
                  <button
                    type="button"
                    className="kw-icon-btn"
                    onClick={() => handleRemoveParam(index)}
                    title="移除参数"
                    disabled={paramsList.length === 1 && !param.name}
                  >
                    <Icon.Trash style={{ width: 14, height: 14, color: 'var(--status-error)' }} />
                  </button>
                </div>
              ))}
            </div>
          </div>

          <footer className="kw-modal-footer">
            <Button type="button" variant="outline" onClick={onClose}>
              取消
            </Button>
            <Button type="submit" variant="accent">
              <Icon.Check style={{ width: 14, height: 14 }} />
              <span>{isFork ? '保存派生理论' : isEdit ? '保存理论修改' : '确认入库'}</span>
            </Button>
          </footer>
        </form>
      </div>
    </div>
  )
}
