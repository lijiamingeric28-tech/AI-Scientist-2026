import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary'
import './styles.css'
import './frontend-v1.css'
import './research-results.css'

// Render with the installed fonts while the optional web stylesheet loads.
const webFonts = document.querySelector('link[data-ui-fonts]')
if (webFonts) {
  const enableFonts = () => { webFonts.media = 'all' }
  if (webFonts.sheet) enableFonts()
  else webFonts.addEventListener('load', enableFonts, { once: true })
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
)
