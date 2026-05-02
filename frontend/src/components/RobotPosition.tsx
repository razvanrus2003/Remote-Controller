import { useState, useEffect } from 'react'
import '../styles/RobotPosition.css'

interface Position {
  x: number
  y: number
  angle: number
}

interface HistoryPoint {
  x: number
  y: number
  timestamp: number
}

export default function RobotPosition() {
  const [position, _setPosition] = useState<Position>({ x: 50, y: 50, angle: 0 })
  const [history, _setHistory] = useState<HistoryPoint[]>([])
  const [speedHistory, _setSpeedHistory] = useState<number[]>([])

  useEffect(() => {
    // TODO: Integrate real position data from /position endpoint
    // Example:
    // const fetchPositionData = async () => {
    //   try {
    //     const response = await axios.get(`${controllerUrl}/position`)
    //     setPosition(response.data)
    //     setHistory(prev => [...prev.slice(-99), { x: response.data.x, y: response.data.y, timestamp: Date.now() }])
    //     setSpeedHistory(prev => [...prev.slice(-99), response.data.speed || 0])
    //   } catch (error) {
    //     console.error('Failed to fetch position data:', error)
    //   }
    // }
    // const interval = setInterval(fetchPositionData, 500)
    // return () => clearInterval(interval)
  }, [])

  return (
    <div className="position-panel">
      <h2>Robot Position & Telemetry</h2>
      
      <div className="position-grid">
        <div className="position-map">
          <svg viewBox="0 0 200 200" className="map-canvas">
            {/* Grid background */}
            <defs>
              <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
                <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#e0e0e0" strokeWidth="0.5"/>
              </pattern>
            </defs>
            <rect width="200" height="200" fill="url(#grid)" />
            
            {/* Robot trail */}
            {history.length > 1 && (
              <polyline
                points={history.map(p => `${Math.min(200, Math.max(0, p.x))},${Math.min(200, Math.max(0, p.y))}`).join(' ')}
                fill="none"
                stroke="#4CAF50"
                strokeWidth="1"
                opacity="0.5"
              />
            )}
            
            {/* Robot position */}
            <g transform={`translate(${Math.min(200, Math.max(0, position.x))},${Math.min(200, Math.max(0, position.y))})`}>
              <circle cx="0" cy="0" r="5" fill="#2196F3" />
              <line x1="0" y1="0" x2={8 * Math.cos(position.angle * Math.PI / 180)} y2={8 * Math.sin(position.angle * Math.PI / 180)} stroke="#FF9800" strokeWidth="1.5" />
            </g>
          </svg>
          <p className="map-label">Position Map</p>
        </div>

        <div className="position-stats">
          <div className="stat-item">
            <label>X Position</label>
            <div className="stat-value">{position.x.toFixed(1)}</div>
          </div>
          <div className="stat-item">
            <label>Y Position</label>
            <div className="stat-value">{position.y.toFixed(1)}</div>
          </div>
          <div className="stat-item">
            <label>Angle</label>
            <div className="stat-value">{position.angle.toFixed(1)}°</div>
          </div>
          <div className="stat-item">
            <label>Trail Points</label>
            <div className="stat-value">{history.length}</div>
          </div>
        </div>
      </div>

      <div className="telemetry-graph">
        <h3>Speed History</h3>
        <svg viewBox="0 0 400 150" className="graph-canvas">
          {/* Grid lines */}
          <line x1="0" y1="25" x2="400" y2="25" stroke="#e0e0e0" strokeWidth="1" />
          <line x1="0" y1="75" x2="400" y2="75" stroke="#e0e0e0" strokeWidth="1" />
          <line x1="0" y1="125" x2="400" y2="125" stroke="#e0e0e0" strokeWidth="1" />
          
          {/* Speed line graph */}
          {speedHistory.length > 1 && (
            <polyline
              points={speedHistory.map((speed, i) => `${(i / speedHistory.length) * 400},${150 - (speed / 50) * 125}`).join(' ')}
              fill="none"
              stroke="#FF9800"
              strokeWidth="2"
            />
          )}
          
          {/* Axes */}
          <line x1="0" y1="0" x2="0" y2="150" stroke="#333" strokeWidth="1" />
          <line x1="0" y1="150" x2="400" y2="150" stroke="#333" strokeWidth="1" />
        </svg>
        <p className="graph-label">Speed (km/h)</p>
      </div>
    </div>
  )
}
