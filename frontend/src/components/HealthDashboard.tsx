interface HealthStats {
  cpu_percent: number
  mem_used_mb: number
  mem_total_mb: number
  mem_available_mb: number
  swap_used_mb: number
  swap_free_mb: number
  swap_total_mb: number
  period_sec: number
}

interface HealthDashboardProps {
  healthStats: HealthStats | null
  healthHistory: HealthStats[]
  isConnected: boolean
}

import '../styles/HealthDashboard.css'

export default function HealthDashboard({ healthStats, healthHistory, isConnected }: HealthDashboardProps) {
  if (!healthStats) {
    return (
      <div className="health-dashboard-card">
        <div className="dashboard-header">
          <h2>System Health</h2>
          <div className={`health-status ${isConnected ? 'healthy' : 'unhealthy'}`}>
            {isConnected ? '🟢 Healthy' : '🔴 Unhealthy'}
          </div>
        </div>
        <div className="dashboard-placeholder">Loading...</div>
      </div>
    )
  }

  return (
    <div className="health-dashboard-card">
      <div className="dashboard-header">
        <h2>System Health</h2>
        <div className={`health-status ${isConnected ? 'healthy' : 'unhealthy'}`}>
          {isConnected ? '🟢 Healthy' : '🔴 Unhealthy'}
        </div>
      </div>

      <div className="health-metrics-display">
        <div className="metric-card-display">
          <div className="metric-label">CPU Usage</div>
          <div className="metric-value">{healthStats.cpu_percent.toFixed(1)}%</div>
          <div className="metric-bar">
            <div className="metric-bar-fill" style={{ width: `${Math.min(100, healthStats.cpu_percent)}%` }}></div>
          </div>
        </div>
        <div className="metric-card-display">
          <div className="metric-label">Memory Used</div>
          <div className="metric-value">{healthStats.mem_used_mb.toFixed(0)} MB</div>
          <div className="metric-bar">
            <div className="metric-bar-fill" style={{ width: `${(healthStats.mem_used_mb / healthStats.mem_total_mb) * 100}%` }}></div>
          </div>
        </div>
        <div className="metric-card-display">
          <div className="metric-label">Swap Used</div>
          <div className="metric-value">{healthStats.swap_used_mb.toFixed(0)} MB</div>
          <div className="metric-bar">
            <div className="metric-bar-fill" style={{ width: `${healthStats.swap_total_mb > 0 ? (healthStats.swap_used_mb / healthStats.swap_total_mb) * 100 : 0}%` }}></div>
          </div>
        </div>
      </div>

      {healthHistory.length > 1 && (
        <div className="graphs-display">
          <div className="health-graph-display">
            <h4>CPU Trend</h4>
            <svg viewBox="0 0 300 150" className="graph-svg-display">
              <line x1="0" y1="30" x2="300" y2="30" stroke="#e0e0e0" strokeWidth="0.5" />
              <line x1="0" y1="60" x2="300" y2="60" stroke="#e0e0e0" strokeWidth="0.5" />
              <line x1="0" y1="90" x2="300" y2="90" stroke="#e0e0e0" strokeWidth="0.5" />
              <line x1="0" y1="120" x2="300" y2="120" stroke="#e0e0e0" strokeWidth="0.5" />
              <polyline
                points={healthHistory
                  .map((h, i) => `${(i / Math.max(1, healthHistory.length - 1)) * 300},${135 - (h.cpu_percent / 100) * 135}`)
                  .join(' ')}
                fill="none"
                stroke="#4CAF50"
                strokeWidth="1.5"
              />
              <line x1="0" y1="135" x2="300" y2="135" stroke="#333" strokeWidth="0.5" />
              <line x1="0" y1="0" x2="0" y2="135" stroke="#333" strokeWidth="0.5" />
            </svg>
          </div>

          <div className="health-graph-display">
            <h4>Memory Trend</h4>
            <svg viewBox="0 0 300 150" className="graph-svg-display">
              <line x1="0" y1="30" x2="300" y2="30" stroke="#e0e0e0" strokeWidth="0.5" />
              <line x1="0" y1="60" x2="300" y2="60" stroke="#e0e0e0" strokeWidth="0.5" />
              <line x1="0" y1="90" x2="300" y2="90" stroke="#e0e0e0" strokeWidth="0.5" />
              <line x1="0" y1="120" x2="300" y2="120" stroke="#e0e0e0" strokeWidth="0.5" />
              <polyline
                points={healthHistory
                  .map((h, i) => {
                    const memPercent = (h.mem_used_mb / h.mem_total_mb) * 100
                    return `${(i / Math.max(1, healthHistory.length - 1)) * 300},${135 - (memPercent / 100) * 135}`
                  })
                  .join(' ')}
                fill="none"
                stroke="#2196F3"
                strokeWidth="1.5"
              />
              <line x1="0" y1="135" x2="300" y2="135" stroke="#333" strokeWidth="0.5" />
              <line x1="0" y1="0" x2="0" y2="135" stroke="#333" strokeWidth="0.5" />
            </svg>
          </div>

          <div className="health-graph-display">
            <h4>Swap Trend</h4>
            <svg viewBox="0 0 300 150" className="graph-svg-display">
              <line x1="0" y1="30" x2="300" y2="30" stroke="#e0e0e0" strokeWidth="0.5" />
              <line x1="0" y1="60" x2="300" y2="60" stroke="#e0e0e0" strokeWidth="0.5" />
              <line x1="0" y1="90" x2="300" y2="90" stroke="#e0e0e0" strokeWidth="0.5" />
              <line x1="0" y1="120" x2="300" y2="120" stroke="#e0e0e0" strokeWidth="0.5" />
              <polyline
                points={healthHistory
                  .map((h, i) => {
                    const swapPercent = h.swap_total_mb > 0 ? (h.swap_used_mb / h.swap_total_mb) * 100 : 0
                    return `${(i / Math.max(1, healthHistory.length - 1)) * 300},${135 - (swapPercent / 100) * 135}`
                  })
                  .join(' ')}
                fill="none"
                stroke="#FF9800"
                strokeWidth="1.5"
              />
              <line x1="0" y1="135" x2="300" y2="135" stroke="#333" strokeWidth="0.5" />
              <line x1="0" y1="0" x2="0" y2="135" stroke="#333" strokeWidth="0.5" />
            </svg>
          </div>
        </div>
      )}
    </div>
  )
}
