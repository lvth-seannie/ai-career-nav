import { useEffect, useState } from 'react'
import Sidebar from './components/Sidebar'
import { MenuIcon } from './components/icons'
import CareerAdvisor from './pages/CareerAdvisor'
import MarketInsights from './pages/MarketInsights'
import AIResults from './pages/AIResults'
import { fetchMarketInsights, fetchRoles, submitCareerAnalysis } from './services/api'
import './App.css'

function parseSkills(rawSkills) {
  return rawSkills
    .split(',')
    .map((skill) => skill.trim())
    .filter(Boolean)
}

function App() {
  const [activePage, setActivePage] = useState('advisor')
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)

  const [targetRole, setTargetRole] = useState('Data Engineer')
  const [currentSkills, setCurrentSkills] = useState('Java, Spring Boot, SQL, REST API')
  const [roles, setRoles] = useState([])

  const [insights, setInsights] = useState({ status: 'loading', data: null, error: '' })
  const [analysis, setAnalysis] = useState({ status: 'idle', data: null, error: '' })

  useEffect(() => {
    let cancelled = false

    fetchMarketInsights()
      .then((data) => {
        if (cancelled) return
        setInsights({ status: 'success', data, error: '' })
      })
      .catch((error) => {
        if (cancelled) return
        setInsights({ status: 'error', data: null, error: error.message })
      })

    fetchRoles()
      .then((data) => {
        if (cancelled) return
        setRoles(data)
      })
      .catch(() => {
        // Role list is only used to populate the advisor dropdown; a fetch
        // failure there surfaces via the /analyze error instead.
      })

    return () => {
      cancelled = true
    }
  }, [])

  const handleNavigate = (pageId) => {
    setActivePage(pageId)
    setIsSidebarOpen(false)
  }

  const handleAnalyze = async () => {
    const skills = parseSkills(currentSkills)

    if (!targetRole || skills.length === 0) {
      setAnalysis({ status: 'error', data: null, error: 'Please provide a target role and at least one skill.' })
      return
    }

    setAnalysis({ status: 'loading', data: null, error: '' })

    try {
      const data = await submitCareerAnalysis({ targetRole, currentSkills: skills })
      setAnalysis({ status: 'success', data, error: '' })
      setActivePage('results')
    } catch (error) {
      setAnalysis({ status: 'error', data: null, error: error.message })
    }
  }

  return (
    <div className="app-shell">
      <Sidebar
        activePage={activePage}
        onNavigate={handleNavigate}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
      />

      <div className="app-main">
        <header className="mobile-topbar">
          <button className="icon-btn" onClick={() => setIsSidebarOpen(true)} aria-label="Open navigation">
            <MenuIcon />
          </button>
          <span className="brand-name">AI Career Navigator</span>
        </header>

        <main className="main-content">
          {activePage === 'advisor' && (
            <CareerAdvisor
              roles={roles}
              targetRole={targetRole}
              setTargetRole={setTargetRole}
              currentSkills={currentSkills}
              setCurrentSkills={setCurrentSkills}
              onAnalyze={handleAnalyze}
              status={analysis.status}
              errorMessage={analysis.error}
            />
          )}

          {activePage === 'insights' && (
            <MarketInsights
              data={insights.data}
              status={insights.status}
              errorMessage={insights.error}
            />
          )}

          {activePage === 'results' && (
            <AIResults
              targetRole={targetRole}
              results={analysis.data}
              status={analysis.status}
              errorMessage={analysis.error}
            />
          )}
        </main>
      </div>
    </div>
  )
}

export default App
