import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Icon } from '@/components/icons'
import { KNOWLEDGE_CATEGORIES } from './knowledgeConstants'
import { getKnowledgeItem, getKnowledgeCategories, createKnowledgeCategory as createCategoryRequest } from '@/services/api'
import { categoryMutationResult } from '@/lib/knowledgeCategories'
import { acceptKnowledgeConflict, buildKnowledgePayload, createKnowledgeCategory, createKnowledgeDraft, createSaveGate, knowledgeDraftComparison, loadKnowledgeConflict, propertyChoices, splitValues } from './knowledgeReading'
import { EntryOverview, SourcesList, useReadingFocus } from './knowledgeReadingParts'
import KnowledgeLinkPicker from './KnowledgeLinkPicker'
import './knowledgeReading.css'

export default function KnowledgeEditorModal({
  isOpen, initialData, mode = 'create', existingCategories, knownProperties = [],
  readOnly = false, pending = false, connecting = false, onSave, onClose, onReloadLatest, onCreateCategory, categoryCatalogReady, onReconnect,
}) {
  const [draft, setDraft] = useState(() => createKnowledgeDraft(initialData, mode))
  const [editingBase, setEditingBase] = useState(initialData)
  const [conflict, setConflict] = useState(null)
  const [loadingLatest, setLoadingLatest] = useState(false)
  const [recoveryError, setRecoveryError] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [discardOpen, setDiscardOpen] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [propertySearch, setPropertySearch] = useState('')
  const [createdCategories, setCreatedCategories] = useState([])
  const [categoryCreateOpen, setCategoryCreateOpen] = useState(false)
  const [categoryName, setCategoryName] = useState('')
  const [categoryError, setCategoryError] = useState('')
  const [categorySaving, setCategorySaving] = useState(false)
  const [standaloneCatalog, setStandaloneCatalog] = useState(null)
  const [categoryLoadError, setCategoryLoadError] = useState('')
  const [categoryReload, reloadCategories] = useState(0)
  const categoryGate = useRef(createSaveGate())
  const categoryInput = useRef(null), categorySelect = useRef(null)
  const baseline = useRef(JSON.stringify(createKnowledgeDraft(initialData, mode)))
  const gate = useRef(createSaveGate())
  const recoverySequence = useRef(0)
  const ref = useRef(null)
  const discardRef = useRef(null)
  const locked = readOnly || pending || saving || categorySaving
  const categoriesReady = categoryCatalogReady ?? (Array.isArray(existingCategories) || standaloneCatalog !== null)
  const dirty = JSON.stringify(draft) !== baseline.current || Boolean(categoryName.trim())
  const requestClose = () => {
    if (saving || categorySaving || gate.current.pending || categoryGate.current.pending) return
    if (dirty) setDiscardOpen(true)
    else onClose?.()
  }
  useReadingFocus(ref, Boolean(isOpen), requestClose, true)
  useReadingFocus(discardRef, discardOpen, () => setDiscardOpen(false), true)
  useEffect(() => {
    if (!isOpen) return
    const next = createKnowledgeDraft(initialData, mode)
    setDraft(next); baseline.current = JSON.stringify(next)
    setEditingBase(initialData); setConflict(null); setLoadingLatest(false); setRecoveryError('')
    setError(''); setDiscardOpen(false); setPreviewOpen(false); setPropertySearch('')
    setCreatedCategories([]); setCategoryCreateOpen(false); setCategoryName(''); setCategoryError('')
    return () => { recoverySequence.current += 1 }
  }, [isOpen, initialData?.id, mode])
  useEffect(() => {
    if (!isOpen || existingCategories) return undefined
    const controller = new AbortController()
    setCategoryLoadError('')
    getKnowledgeCategories({ signal: controller.signal }).then(result => {
      if (!Array.isArray(result?.items)) throw new Error('分类目录响应不完整')
      if (!controller.signal.aborted) setStandaloneCatalog(result.items)
    }).catch(failure => { if (!controller.signal.aborted) setCategoryLoadError(failure.message || '无法读取分类目录') })
    return () => controller.abort()
  }, [isOpen, existingCategories, categoryReload])
  const categories = useMemo(() => {
    const catalog = existingCategories || standaloneCatalog || KNOWLEDGE_CATEGORIES
    const unique = new Map(catalog.filter(category => category.id !== 'all').map(category => [category.id, category]))
    for (const category of createdCategories) if (category.id !== 'all') unique.set(category.id, category)
    return [...unique.values()]
  }, [existingCategories, standaloneCatalog, createdCategories])
  const categoryUnavailable = categoriesReady && !categories.some(category => category.id === draft.category)
  useEffect(() => { if (categoryCreateOpen) categoryInput.current?.focus() }, [categoryCreateOpen])
  const properties = propertyChoices(splitValues(draft.propertiesText), knownProperties)
  const matchingProperties = knownProperties.filter(property => !propertySearch || `${property.id} ${property.label}`.toLocaleLowerCase().includes(propertySearch.toLocaleLowerCase()))
  const change = (field, value) => setDraft(previous => ({ ...previous, [field]: value }))
  const cancelCategory = () => { setCategoryCreateOpen(false); setCategoryName(''); setCategoryError(''); categorySelect.current?.focus() }
  const confirmCategory = async () => {
    if (locked || !categoriesReady || categoryGate.current.pending) return
    try {
      const proposed = createKnowledgeCategory(categoryName, categories)
      setCategorySaving(true); setCategoryError('')
      const result = await categoryGate.current.run(async () => categoryMutationResult(
        await (onCreateCategory ? onCreateCategory(proposed.label) : createCategoryRequest({ label: proposed.label })), 'create'))
      const category = result.value.category
      setCreatedCategories(previous => [...previous, category]); change('category', category.id); cancelCategory()
    } catch (failure) { setCategoryError(failure.message); categoryInput.current?.focus() }
    finally { setCategorySaving(false) }
  }
  const changeParam = (index, field, value) => setDraft(previous => ({ ...previous, parameters: previous.parameters.map((parameter, current) => current === index ? { ...parameter, [field]: value } : parameter) }))
  const addProperty = value => {
    if (!value.trim()) return
    const property = propertyChoices([value.trim()], knownProperties)[0]
    change('propertiesText', [...new Set([...splitValues(draft.propertiesText), property.id])].join(', '))
    setPropertySearch('')
  }
  const submit = async event => {
    event.preventDefault()
    if (locked || conflict || categoryCreateOpen || !categoriesReady || categoryUnavailable || gate.current.pending) return
    setError('')
    let payload
    try { payload = buildKnowledgePayload(draft, editingBase, mode) }
    catch (failure) { setError(failure.message); return }
    setSaving(true)
    try {
      const result = await gate.current.run(() => {
        if (!onSave) throw new Error('保存服务不可用，请稍后重试')
        return onSave(payload, mode)
      })
      if (result.saved) { baseline.current = JSON.stringify(draft); onClose?.() }
    } catch (failure) {
      setError(failure.message || '保存失败。编辑内容已保留，请重试。')
      if (failure.status === 409 && mode === 'edit') { setConflict({ latest: null }); setRecoveryError('') }
    }
    finally { setSaving(false) }
  }
  const reloadLatest = async () => {
    if (loadingLatest || !editingBase?.id) return
    const sequence = ++recoverySequence.current
    setLoadingLatest(true); setRecoveryError('')
    try {
      const latest = await loadKnowledgeConflict(editingBase, onReloadLatest || getKnowledgeItem)
      if (sequence === recoverySequence.current) setConflict({ latest })
    } catch (failure) { if (sequence === recoverySequence.current) setRecoveryError(failure.message || '读取最新版本失败，请重试') }
    finally { if (sequence === recoverySequence.current) setLoadingLatest(false) }
  }
  const acceptLatest = () => {
    try {
      const accepted = acceptKnowledgeConflict(draft, editingBase, conflict.latest)
      setEditingBase(accepted.base); setConflict(null); setRecoveryError(''); setError('')
    } catch (failure) { setRecoveryError(failure.message) }
  }
  if (!isOpen) return null
  const preview = {
    title: draft.title, formula: draft.formula, description: draft.description,
    conditions: draft.conditionsText.split('\n').filter(Boolean), parameters: draft.parameters,
    properties: splitValues(draft.propertiesText), sources: draft.sourcesText,
  }
  const title = mode === 'fork' ? '派生理论知识' : mode === 'edit' ? '编辑理论知识' : '新增理论知识'
  return <div className="kr-editor-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) requestClose() }}>
    <div className="kr-editor" ref={ref} role="dialog" aria-modal="true" aria-labelledby="kr-editor-title" tabIndex={-1} aria-busy={saving}>
      <header className="kr-editor-header"><div><span className="kr-eyebrow">知识工作台</span><h3 id="kr-editor-title">{title}</h3></div>
        <button type="button" className="kr-icon-button" disabled={saving} aria-label="关闭编辑器" onClick={requestClose}><Icon.Close /></button></header>
      {mode === 'edit' && !initialData?.is_user && <p className="kr-editor-notice">保存为用户修改版本，内置来源保留原有归属；可从条目操作中恢复默认。</p>}
      {readOnly && !connecting && <div className="kr-editor-notice" role="status">当前知识库为只读状态，草稿已保留。<button type="button" className="kr-button" disabled={saving || categorySaving} onClick={onReconnect || (() => reloadCategories(value => value + 1))}>重新连接知识库</button></div>}
      {initialData?.report_copy && <p className="kr-editor-notice">原条目当前不可用。本次从报告复制为独立用户知识，报告来源记录保留在参考来源中。</p>}
      {error && <div role="alert" className="kr-error">{error}<span>编辑内容已保留。</span></div>}
      {conflict && <section className="kr-conflict" aria-label="修订冲突恢复">
        <div className="kr-conflict-header"><div><strong>条目已被其他修改更新</strong><p>当前草稿基于修订 {editingBase?.revision ?? 0}。读取并核对最新内容后，可保留草稿继续编辑。</p></div>
          <button type="button" className="kr-button" disabled={loadingLatest || saving} onClick={reloadLatest}>{loadingLatest ? '正在读取最新版本…' : conflict.latest ? '重新读取最新版本' : '读取最新版本进行比较'}</button></div>
        {recoveryError && <p className="kr-error" role="alert">{recoveryError}</p>}
        {conflict.latest && <><div className="kr-conflict-comparison"><table><caption>最新版本（修订 {conflict.latest.revision}）与当前草稿比较</caption><thead><tr><th>字段</th><th>最新版本</th><th>当前草稿</th></tr></thead><tbody>
          {knowledgeDraftComparison(draft, conflict.latest).map(row => <tr key={row.field}><th scope="row">{row.label}</th><td><pre>{row.latest || '未提供'}</pre></td><td><pre>{row.draft || '未提供'}</pre></td></tr>)}
        </tbody></table>{knowledgeDraftComparison(draft, conflict.latest).length === 0 && <p>当前草稿与最新版本内容相同。</p>}</div>
          <button type="button" className="kr-button kr-button-accent" disabled={saving || loadingLatest || readOnly} onClick={acceptLatest}>保留草稿，基于最新版本继续</button></>}
      </section>}
      <div className="kr-mobile-preview-switch"><button className="kr-button" type="button" aria-pressed={!previewOpen} onClick={() => setPreviewOpen(false)}><Icon.Edit />编辑</button>
        <button className="kr-button" type="button" aria-pressed={previewOpen} onClick={() => setPreviewOpen(true)}><Icon.Eye />预览</button></div>
      <form className={`kr-editor-form ${previewOpen ? 'kr-show-preview' : ''}`} onSubmit={submit}>
        <div className="kr-editor-columns">
          <div className="kr-editor-fields">
            <fieldset className="kr-form-section" disabled={locked}><legend>基本信息</legend>
              <label className="kr-field">理论名称与定律标题 <span className="kr-muted">必填</span><input className="kr-input" data-initial-focus value={draft.title} onChange={event => change('title', event.target.value)} placeholder="填写科学理论或模型名称" required /></label>
              <div className="kr-form-row"><div className="kr-field"><label htmlFor="kr-category-select">知识分类</label><div className="kr-category-control"><select id="kr-category-select" ref={categorySelect} className="kr-select" aria-label="知识分类" value={draft.category} onChange={event => change('category', event.target.value)}>{categoryUnavailable && <option value={draft.category} disabled>{initialData?.category_label || draft.category}（分类不可用）</option>}{categories.map(category => <option key={category.id} value={category.id}>{category.label}{category.is_custom ? ' · 自定义' : ''}</option>)}</select><button className="kr-button" type="button" disabled={categoryCreateOpen || !categoriesReady} aria-expanded={categoryCreateOpen} aria-controls="kr-category-create" onClick={() => setCategoryCreateOpen(true)}><Icon.Plus />新建分类</button></div>{createdCategories.some(category => category.id === draft.category) && <small className="kr-category-note">分类已独立保存，关闭编辑器后仍会保留</small>}{!categoriesReady && <small className="kr-muted">正在读取分类目录…</small>}{categoryUnavailable && <small className="kr-category-error">该分类当前不可用，请重新选择，知识草稿已保留。</small>}{categoryLoadError && <span role="alert" className="kr-category-error">{categoryLoadError}<button className="kr-button" type="button" onClick={() => reloadCategories(value => value + 1)}>重新读取分类</button></span>}</div>
                <label className="kr-field">科研优选<span className="kr-checkbox-row"><input type="checkbox" checked={draft.preferred} onChange={event => change('preferred', event.target.checked)} />优先用于科研推理</span></label></div>
              {categoryCreateOpen && <section className="kr-category-create" id="kr-category-create" aria-label="新建知识分类" onKeyDownCapture={event => {
                if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); cancelCategory() }
              }}><div className="kr-category-create-heading"><Icon.Grid /><strong>新建知识分类</strong></div>
                <label className="kr-field">分类名称<input ref={categoryInput} className="kr-input" value={categoryName} maxLength={40} aria-invalid={Boolean(categoryError)} aria-describedby={`kr-category-create-hint${categoryError ? ' kr-category-create-error' : ''}`} placeholder="例如：星系演化笔记" onChange={event => { setCategoryName(event.target.value); setCategoryError('') }} onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent?.isComposing) { event.preventDefault(); confirmCategory() } }} /></label>
                <p id="kr-category-create-hint">创建后立即保存并自动选中，无需保存知识条目。</p>
                {categoryError && <p className="kr-category-error" id="kr-category-create-error" role="alert">{categoryError}</p>}
                <div className="kr-category-create-actions"><button type="button" className="kr-button" onClick={cancelCategory}>取消新建</button><button type="button" className="kr-button kr-button-accent" onClick={confirmCategory}><Icon.Check />{categorySaving ? '正在创建…' : '创建并选用'}</button></div>
              </section>}
              <label className="kr-field">核心理论阐述<textarea className="kr-textarea" rows={4} value={draft.description} onChange={event => change('description', event.target.value)} placeholder="说明物理机制、适用边界与观测意义" /></label>
            </fieldset>
            <fieldset className="kr-form-section" disabled={locked}><legend>公式与参数</legend>
              <label className="kr-field">LaTeX 科学公式<textarea className="kr-textarea kr-formula-input" rows={3} value={draft.formula} onChange={event => change('formula', event.target.value)} placeholder="例如：L = 4\\pi R^2 \\sigma T^4" /></label>
              <p className="kr-muted">预览保留无法解析的原始公式。</p>
              <div className="kr-parameter-editor">{draft.parameters.map((parameter, index) => <div className="kr-parameter-fields" key={index}>
                {[['name', '参数名'], ['symbol', '符号'], ['range', '取值范围'], ['unit', '单位'], ['desc', '物理说明']].map(([field, label]) => <label className={`kr-field kr-param-${field}`} key={field}>{label}<input className="kr-input" value={parameter[field] || ''} onChange={event => changeParam(index, field, event.target.value)} /></label>)}
                <button type="button" className="kr-icon-button kr-danger" aria-label={`移除参数 ${index + 1}`} onClick={() => change('parameters', draft.parameters.filter((_, current) => current !== index))}><Icon.Trash /></button>
              </div>)}</div>
              <button className="kr-button" type="button" onClick={() => change('parameters', [...draft.parameters, { name: '', symbol: '', range: '', unit: '', desc: '' }])}><Icon.Plus />添加参数</button>
            </fieldset>
            <fieldset className="kr-form-section" disabled={locked}><legend>适用条件</legend><label className="kr-field">物理假定与边界 <span className="kr-muted">每行一条</span>
              <textarea className="kr-textarea" rows={4} value={draft.conditionsText} onChange={event => change('conditionsText', event.target.value)} placeholder="说明适用条件、约束与限制" /></label></fieldset>
            <fieldset className="kr-form-section" disabled={locked}><legend>关联知识</legend>
              <KnowledgeLinkPicker key={`${mode}:${initialData?.id || 'new'}`} value={draft.relatedIds} summaries={editingBase?.relations?.related} categories={categories} excludeId={mode === 'edit' ? editingBase?.id : undefined} disabled={locked} onChange={value => change('relatedIds', value)} />
            </fieldset>
            <fieldset className="kr-form-section" disabled={locked}><legend>物理量与来源</legend>
              <label className="kr-field">搜索已知物理量<input className="kr-input" value={propertySearch} onChange={event => setPropertySearch(event.target.value)} placeholder="按名称或编号搜索，也可添加自定义值" onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); addProperty(propertySearch) } }} /></label>
              {propertySearch && <div className="kr-property-results">{matchingProperties.slice(0, 12).map(property => <button className="kr-button" key={property.id} type="button" onClick={() => addProperty(property.property_id || property.id)}>{property.label || property.id}</button>)}
                <button className="kr-button" type="button" onClick={() => addProperty(propertySearch)}>添加「{propertySearch}」</button></div>}
              <label className="kr-field">关联物理量 <span className="kr-muted">逗号分隔；自定义值保持未绑定</span><input className="kr-input" value={draft.propertiesText} onChange={event => change('propertiesText', event.target.value)} /></label>
              <div className="kr-tags">{properties.map(property => <span key={property.id} className={`kr-tag ${property.bound ? '' : 'kr-unbound'}`}>{property.label}{property.bound ? '' : ' · 未绑定'}</span>)}</div>
              <label className="kr-field">学术标签<input className="kr-input" value={draft.tagsText} onChange={event => change('tagsText', event.target.value)} placeholder="逗号分隔" /></label>
              <label className="kr-field">参考文献与来源<textarea className="kr-textarea" rows={5} value={draft.sourcesText} onChange={event => change('sourcesText', event.target.value)} placeholder="完整引用、DOI、资料出处或科研笔记" /></label>
            </fieldset>
          </div>
          <aside className="kr-editor-preview" aria-label="实时预览"><span className="kr-eyebrow">实时预览</span><h3>{draft.title || '未命名理论'}</h3><EntryOverview item={preview} /><h4>参考来源</h4><SourcesList sources={draft.sourcesText} /></aside>
        </div>
        <footer className="kr-editor-footer"><span className="kr-muted">{saving ? '正在保存…' : dirty ? '有未保存的修改' : '内容已同步至编辑器'}</span><div>
          <button className="kr-button" type="button" disabled={saving || categorySaving || pending} onClick={requestClose}>取消</button><button className="kr-button kr-button-accent" type="submit" disabled={locked || Boolean(conflict) || categoryCreateOpen || !categoriesReady || categoryUnavailable}><Icon.Check />{saving ? '正在保存…' : mode === 'fork' ? '保存派生理论' : '保存知识条目'}</button>
        </div></footer>
      </form>
      {discardOpen && <div className="kr-discard-backdrop"><div className="kr-confirm" ref={discardRef} role="alertdialog" aria-modal="true" aria-labelledby="kr-discard-title" tabIndex={-1}>
        <h3 id="kr-discard-title">放弃未保存的修改？</h3><p>关闭后，本次知识编辑的内容将丢失。{createdCategories.length > 0 && '已独立创建的分类会保留。'}</p><div className="kr-confirm-actions"><button type="button" className="kr-button" data-initial-focus onClick={() => setDiscardOpen(false)}>继续编辑</button>
          <button type="button" className="kr-button kr-danger-button" onClick={() => { setDiscardOpen(false); onClose?.() }}>放弃修改</button></div>
      </div></div>}
    </div>
  </div>
}
