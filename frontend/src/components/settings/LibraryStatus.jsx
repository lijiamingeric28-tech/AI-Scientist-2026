import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import * as api from '@/services/api'

export default function LibraryStatus({ active, onLaunchStudio }) {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!active) return
    let disposed = false
    api.getLibraryStatus()
      .then(v => { if (!disposed) { setStatus(v); setError('') } })
      .catch(e => { if (!disposed) setError(e.message) })
    return () => { disposed = true }
  }, [active])

  const registryOk = status?.registry?.state === 'available'
  const bindingsOk = status?.knowledge_bindings?.state === 'available'
  const contentOk = status?.knowledge_content?.state === 'available'
  const entriesCount = status?.knowledge_content?.entries
  const typesCount = status?.knowledge_content?.types
  const bindingsCount = status?.knowledge_bindings?.bindings

  return (
    <div className="settings-panel-container">
      <div className="settings-panel-intro">
        <h3 className="settings-panel-title">知识库与图谱 (Knowledge &amp; Theory)</h3>
        <p className="settings-panel-desc">
          统一管理天体物理性质注册表、理论知识图谱、自定义理论类别/条目与“科研优选”策略（已从首页顶栏收纳至此处统一配置）。
        </p>
      </div>

      <section className="settings-config-section">
        <div className="settings-config-section-header">
          <span className="settings-config-section-title">科学库状态与覆盖 (CORPUS &amp; BINDINGS)</span>
          <span className={`settings-config-section-badge${error ? ' is-warn' : ''}`}>
            {error ? '读取异常' : !status ? '正在检测…' : registryOk && bindingsOk ? '本地科学库已就绪' : '部分受限'}
          </span>
        </div>

        {error ? (
          <div className="resource-error" role="alert">{error}</div>
        ) : !status ? (
          <div className="settings-config-rows-group">
            <div className="settings-config-row">
              <div className="settings-config-row-label">
                <strong>正在读取发布状态…</strong>
                <span>检查性质注册表与知识绑定索引</span>
              </div>
              <div className="settings-config-row-control">
                <span className="settings-status-pill">检测中</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="settings-config-rows-group">
            <div className="settings-config-row">
              <div className="settings-config-row-label">
                <strong>物理性质注册表 (Property Registry)</strong>
                <span>用于意图澄清、物理量标准化与跨文献质检的标准性质定义</span>
              </div>
              <div className="settings-config-row-control">
                <span className={`settings-status-pill ${registryOk ? 'is-ok' : 'is-warn'}`}>
                  {registryOk ? '已安装 · 运行正常' : `不可用（${status.registry?.reason || '未记录'}）`}
                </span>
              </div>
            </div>

            <div className="settings-config-row">
              <div className="settings-config-row-label">
                <strong>理论知识条目与分类 (Theoretical Corpus)</strong>
                <span>包含物理定律、状态方程、测量与消光及用户自定义扩展类别</span>
              </div>
              <div className="settings-config-row-control">
                <span className={`settings-status-pill ${contentOk ? '' : 'is-warn'}`}>
                  {contentOk && Number.isFinite(entriesCount) && Number.isFinite(typesCount)
                    ? `${entriesCount} 张知识卡 · ${typesCount} 大类`
                    : '使用内置理论语料'}
                </span>
              </div>
            </div>

            <div className="settings-config-row">
              <div className="settings-config-row-label">
                <strong>性质关联绑定 (Knowledge Bindings)</strong>
                <span>已将理论机制、公式和界限条件绑定到对应天文物理性质</span>
              </div>
              <div className="settings-config-row-control">
                <span className={`settings-status-pill ${bindingsOk ? 'is-ok' : 'is-warn'}`}>
                  {bindingsOk
                    ? Number.isFinite(bindingsCount)
                      ? `已安装 · ${bindingsCount} 项性质绑定`
                      : '已安装 · 关联覆盖完整'
                    : `不可用（${status.knowledge_bindings?.reason || '未记录'}）`}
                </span>
              </div>
            </div>
          </div>
        )}
      </section>

      <section className="settings-config-section">
        <div className="settings-config-section-header">
          <span className="settings-config-section-title">大型配置工作台 (KNOWLEDGE WORKBENCH)</span>
        </div>

        <div className="settings-knowledge-launcher">
          <div className="settings-knowledge-launcher-left">
            <div className="settings-knowledge-launcher-icon" aria-hidden="true">
              <Icon.Atom style={{ width: 20, height: 20 }} />
            </div>
            <div className="settings-knowledge-launcher-text">
              <h4>进入知识图谱与理论库配置大界面</h4>
              <p>
                展开全宽设置工作台，支持星系关系图谱探索、分类矩阵浏览、自定义类别新建、理论条目增删改派生与标星“科研优选”。
              </p>
            </div>
          </div>
          <Button
            variant="accent"
            size="sm"
            onClick={() => onLaunchStudio?.('graph')}
            style={{ whiteSpace: 'nowrap', flexShrink: 0 }}
          >
            <span>打开配置工作台</span>
            <Icon.ArrowRight style={{ width: 14, height: 14 }} />
          </Button>
        </div>

        <div className="settings-config-rows-group">
          <div className="settings-config-row">
            <div className="settings-config-row-label">
              <strong>按指定初始视图进入 (Quick Launch)</strong>
              <span>选择直接以关系图谱或结构化分类矩阵模式打开大型配置工作台</span>
            </div>
            <div className="settings-config-row-control">
              <button
                type="button"
                className="settings-action-inline"
                onClick={() => onLaunchStudio?.('graph')}
              >
                <Icon.Network style={{ width: 14, height: 14 }} />
                <span>打开知识图谱</span>
              </button>
              <button
                type="button"
                className="settings-action-inline"
                onClick={() => onLaunchStudio?.('matrix')}
              >
                <Icon.Grid style={{ width: 14, height: 14 }} />
                <span>打开分类矩阵</span>
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
