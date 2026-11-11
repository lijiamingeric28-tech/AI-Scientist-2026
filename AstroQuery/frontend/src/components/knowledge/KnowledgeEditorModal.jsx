import React, { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { LatexMath } from '@/components/results/LatexMath'
import { KNOWLEDGE_CATEGORIES } from './knowledgeConstants'

export default function KnowledgeEditorModal({ isOpen, initialData, mode = 'create', onSave, onClose }) {
  if (!isOpen) return null

  const isFork = mode === 'fork'
  const isEdit = mode === 'edit'

  const [title, setTitle] = useState('')
  const [category, setCategory] = useState('user_private')
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

  useEffect(() => {
    if (initialData) {
      setTitle(isFork ? `${initialData.title || initialData.name || ''} (派生版)` : initialData.title || initialData.name || '')
      setCategory(isFork ? 'user_private' : initialData.category || 'user_private')
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
      setCategory('user_private')
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
  }, [initialData, isFork, isOpen])

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
      category,
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
      ...(isFork ? { base_id: initialData?.id } : {}),
      updated_at: new Date().toISOString(),
    }

    onSave(payload, isFork ? 'fork' : isEdit ? 'edit' : 'create')
  }

  const categoriesOptions = KNOWLEDGE_CATEGORIES.filter(c => c.id !== 'all')

  return (
    <div className="kw-modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="kw-modal-dialog" onClick={e => e.stopPropagation()}>
        <header className="kw-modal-header">
          <h3>
            <Icon.Edit style={{ width: 18, height: 18, color: 'var(--accent)' }} />
            <span>{isFork ? '派生自已有理论知识' : isEdit ? '编辑理论知识' : '新增理论知识'}</span>
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
            <div className="kw-form-group">
              <label className="kw-form-label">
                <span>知识分类</span>
              </label>
              <select
                className="kw-select"
                value={category}
                onChange={e => setCategory(e.target.value)}
              >
                {categoriesOptions.map(c => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="kw-form-group">
              <label className="kw-form-label">
                <span>用户优选标记</span>
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
              <span className="kw-form-hint">支持标准 KaTeX 语法</span>
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
                  <LatexMath math={formula} displayMode />
                </div>
              </div>
            )}
          </div>

          <div className="kw-form-group">
            <label className="kw-form-label">
              <span>理论陈述与物理机制说明</span>
            </label>
            <textarea
              className="kw-textarea"
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="详细阐述该理论的核心物理图像、推导假定、适用天体范畴或观测反演方法..."
            />
          </div>

          <div className="kw-form-group">
            <label className="kw-form-label">
              <span>适用条件与假定 (每行一条)</span>
            </label>
            <textarea
              className="kw-textarea"
              style={{ minHeight: 60 }}
              value={conditionsText}
              onChange={e => setConditionsText(e.target.value)}
              placeholder="局域热动平衡(LTE)&#10;极端相对论费米气体&#10;消光比值 R_V = 3.1"
            />
          </div>

          <div className="kw-form-group">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <label className="kw-form-label" style={{ margin: 0 }}>
                <span>物理参数范围与常量定义</span>
              </label>
              <Button type="button" variant="outline" size="sm" onClick={handleAddParam}>
                <Icon.Plus style={{ width: 12, height: 12 }} />
                <span>增加参数</span>
              </Button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {paramsList.map((p, idx) => (
                <div key={idx} style={{ display: 'grid', gridTemplateColumns: '100px 90px 110px 80px 1fr 32px', gap: 6, alignItems: 'center' }}>
                  <input
                    type="text"
                    className="kw-input"
                    placeholder="标识符(T_eff)"
                    value={p.name}
                    onChange={e => handleParamChange(idx, 'name', e.target.value)}
                    style={{ padding: '4px 8px', fontSize: 12 }}
                  />
                  <input
                    type="text"
                    className="kw-input"
                    placeholder="LaTeX符号"
                    value={p.symbol}
                    onChange={e => handleParamChange(idx, 'symbol', e.target.value)}
                    style={{ padding: '4px 8px', fontSize: 12 }}
                  />
                  <input
                    type="text"
                    className="kw-input"
                    placeholder="有效区间"
                    value={p.range}
                    onChange={e => handleParamChange(idx, 'range', e.target.value)}
                    style={{ padding: '4px 8px', fontSize: 12 }}
                  />
                  <input
                    type="text"
                    className="kw-input"
                    placeholder="物理单位"
                    value={p.unit}
                    onChange={e => handleParamChange(idx, 'unit', e.target.value)}
                    style={{ padding: '4px 8px', fontSize: 12 }}
                  />
                  <input
                    type="text"
                    className="kw-input"
                    placeholder="参数释义"
                    value={p.desc}
                    onChange={e => handleParamChange(idx, 'desc', e.target.value)}
                    style={{ padding: '4px 8px', fontSize: 12 }}
                  />
                  <button
                    type="button"
                    className="kw-icon-btn"
                    onClick={() => handleRemoveParam(idx)}
                    title="移除"
                  >
                    <Icon.Trash style={{ width: 14, height: 14 }} />
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div className="kw-form-group">
              <label className="kw-form-label">
                <span>关联天体物理性质</span>
                <span className="kw-form-hint">逗号分隔</span>
              </label>
              <input
                type="text"
                className="kw-input"
                value={propertiesText}
                onChange={e => setPropertiesText(e.target.value)}
                placeholder="Luminosity, Effective Temperature, Radius"
              />
            </div>
            <div className="kw-form-group">
              <label className="kw-form-label">
                <span>分类检索标签</span>
                <span className="kw-form-hint">逗号分隔</span>
              </label>
              <input
                type="text"
                className="kw-input"
                value={tagsText}
                onChange={e => setTagsText(e.target.value)}
                placeholder="黑体辐射, 恒星结构, 观测推导"
              />
            </div>
          </div>

          <div className="kw-form-group">
            <label className="kw-form-label">
              <span>文献出处与科研参考 (Sources)</span>
            </label>
            <input
              type="text"
              className="kw-input"
              value={sources}
              onChange={e => setSources(e.target.value)}
              placeholder="例如：Stefan (1879); Carroll & Ostlie (2017) Intro to Modern Astrophysics"
            />
          </div>
        </form>

        <footer className="kw-modal-footer">
          <Button type="button" variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button type="button" variant="default" onClick={handleSubmit}>
            <Icon.Check style={{ width: 14, height: 14 }} />
            <span>{isFork ? '保存派生理论' : '保存理论知识'}</span>
          </Button>
        </footer>
      </div>
    </div>
  )
}
