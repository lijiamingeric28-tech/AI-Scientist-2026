import {lazy,Suspense} from 'react'
import {useDialogFocus} from '@/hooks/useDialogFocus'
const RegistryWorkspace=lazy(()=>import('@/components/registry/RegistryWorkspace'))

export default function SettingsRegistryStudio({open,dismissal,onBackToSettings,onClose,onKnowledge}) {
  const ref=useDialogFocus(open,onClose,{trap:true})
  if(!open)return null
  return <div className="settings-overlay" data-closing={dismissal.closing||undefined} onClick={onClose}><section ref={ref} role="dialog" aria-modal="true" aria-label="天体与性质规范工作台" tabIndex={-1} className="settings-studio-dialog animate-modal-in" data-closing={dismissal.closing||undefined} onAnimationEnd={dismissal.onAnimationEnd} onKeyDownCapture={dismissal.onKeyDownCapture} onClick={e=>e.stopPropagation()}><div className="settings-studio-body"><Suspense fallback={<p role="status">正在加载规范工作台…</p>}><RegistryWorkspace onBack={onBackToSettings} onClose={onClose} onKnowledge={onKnowledge}/></Suspense></div></section></div>
}
