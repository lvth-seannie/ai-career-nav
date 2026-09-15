import { ArrowRightIcon } from '../components/icons'

function CareerAdvisor({ roles, targetRole, setTargetRole, currentSkills, setCurrentSkills, onAnalyze, status, errorMessage }) {
  const isLoading = status === 'loading'
  const rolesLoaded = roles.length > 0

  return (
    <div className="page">
      <header className="page-header">
        <p className="page-eyebrow">Step 1</p>
        <h1 className="page-title">Career Advisor</h1>
        <p className="page-subtitle">
          Tell us where you want to go and what you already know. We'll send it to the AI
          pipeline to calculate your skill gap and build a personalized roadmap.
        </p>
      </header>

      <div className="card card--form">
        <div className="field">
          <label className="label" htmlFor="target-role">
            Target career role
          </label>
          <select
            id="target-role"
            className="input-field"
            value={targetRole}
            onChange={(event) => setTargetRole(event.target.value)}
            disabled={!rolesLoaded}
          >
            {rolesLoaded ? (
              roles.map((role) => (
                <option key={role.id} value={role.label}>
                  {role.label}
                </option>
              ))
            ) : (
              <option>Loading roles…</option>
            )}
          </select>
        </div>

        <div className="field">
          <label className="label" htmlFor="current-skills">
            Current skills (comma separated)
          </label>
          <input
            id="current-skills"
            type="text"
            className="input-field"
            value={currentSkills}
            onChange={(event) => setCurrentSkills(event.target.value)}
            placeholder="e.g. Java, SQL, React"
          />
        </div>

        {status === 'error' && (
          <div className="alert alert--error">
            {errorMessage || 'Something went wrong while running the analysis. Please try again.'}
          </div>
        )}

        <button className="btn-primary" onClick={onAnalyze} disabled={isLoading}>
          {isLoading ? (
            'Running AI analysis…'
          ) : (
            <>
              Run AI Analysis <ArrowRightIcon />
            </>
          )}
        </button>
      </div>
    </div>
  )
}

export default CareerAdvisor
