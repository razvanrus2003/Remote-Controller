import { useState, useEffect, useMemo } from 'react'
import axios from 'axios'
import '../styles/RobotPosition.css'

interface PositionTelemetry {
  timestamp: number
  robot_x: number
  robot_y: number
  robot_ang: number
  robot_ang_spd: number
  robot_lin_spd: number
  target_x: number
  target_y: number
  target_ang: number
  target_lin_spd: number
  enc_c1: number
  enc_c2: number
}

interface HistoryPoint {
  x: number
  y: number
  timestamp: number
}

const EMPTY_TELEMETRY: PositionTelemetry = {
  timestamp: 0,
  robot_x: 0,
  robot_y: 0,
  robot_ang: 0,
  robot_ang_spd: 0,
  robot_lin_spd: 0,
  target_x: 0,
  target_y: 0,
  target_ang: 0,
  target_lin_spd: 0,
  enc_c1: 0,
  enc_c2: 0,
}

export default function RobotPosition({ resetTrigger = 0 }: { resetTrigger?: number }) {
  const [telemetry, setTelemetry] = useState<PositionTelemetry>(EMPTY_TELEMETRY)
  const [history, setHistory] = useState<HistoryPoint[]>([])
  const [speedHistory, setSpeedHistory] = useState<number[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [isResetView, setIsResetView] = useState(false)

  const controllerUrl = 'http://192.168.1.132:5000'

  const parsePositionString = (payload: string): PositionTelemetry | null => {
    const parts = payload.split(',').map((part) => part.trim())
    const parsed: Partial<PositionTelemetry> = {}

    for (const part of parts) {
      const [key, value] = part.split('=').map((item) => item.trim())
      if (!key || value === undefined) {
        continue
      }

      const numericValue = Number(value)
      if (Number.isNaN(numericValue)) {
        continue
      }

      if (
        key === 'timestamp' ||
        key === 'robot_x' ||
        key === 'robot_y' ||
        key === 'robot_ang' ||
        key === 'robot_ang_spd' ||
        key === 'robot_lin_spd' ||
        key === 'target_x' ||
        key === 'target_y' ||
        key === 'target_ang' ||
        key === 'target_lin_spd' ||
        key === 'enc_c1' ||
        key === 'enc_c2'
      ) {
        parsed[key] = numericValue
      }
    }

    if (
      parsed.timestamp === undefined ||
      parsed.robot_x === undefined ||
      parsed.robot_y === undefined ||
      parsed.robot_ang === undefined ||
      parsed.robot_ang_spd === undefined ||
      parsed.robot_lin_spd === undefined ||
      parsed.target_x === undefined ||
      parsed.target_y === undefined ||
      parsed.target_ang === undefined ||
      parsed.target_lin_spd === undefined ||
      parsed.enc_c1 === undefined ||
      parsed.enc_c2 === undefined
    ) {
      return null
    }

    return parsed as PositionTelemetry
  }

  const parsePositionObject = (payload: Record<string, unknown>): PositionTelemetry | null => {
    const result: Partial<PositionTelemetry> = {}
    const keys: Array<keyof PositionTelemetry> = [
      'timestamp',
      'robot_x',
      'robot_y',
      'robot_ang',
      'robot_ang_spd',
      'robot_lin_spd',
      'target_x',
      'target_y',
      'target_ang',
      'target_lin_spd',
      'enc_c1',
      'enc_c2',
    ]

    for (const key of keys) {
      const value = payload[key]
      if (typeof value !== 'number') {
        return null
      }
      result[key] = value
    }

    return result as PositionTelemetry
  }

  useEffect(() => {
    let isMounted = true

    const fetchPositionData = async () => {
      try {
        const response = await axios.get(`${controllerUrl}/position`)
        const data = response.data as unknown

        let parsed: PositionTelemetry | null = null
        if (typeof data === 'string') {
          parsed = parsePositionString(data)
        } else if (typeof data === 'object' && data !== null) {
          const obj = data as Record<string, unknown>
          if (typeof obj.position === 'string') {
            parsed = parsePositionString(obj.position)
          } else if (typeof obj.position === 'object' && obj.position !== null) {
            parsed = parsePositionObject(obj.position as Record<string, unknown>)
          } else {
            parsed = parsePositionObject(obj)
          }
        }

        if (!isMounted || !parsed) {
          if (isMounted) {
            setIsConnected(false)
          }
          return
        }

        setTelemetry(parsed)
        setHistory((prev) => [
          ...prev.slice(-99),
          { x: parsed.robot_x, y: parsed.robot_y, timestamp: parsed.timestamp },
        ])
        setSpeedHistory((prev) => [...prev.slice(-119), parsed.robot_lin_spd])
        setIsConnected(true)
      } catch (error) {
        console.error('Failed to fetch position data:', error)
        if (isMounted) {
          setIsConnected(false)
        }
      }
    }

    void fetchPositionData()
    const interval = window.setInterval(() => {
      void fetchPositionData()
    }, 500)

    return () => {
      isMounted = false
      window.clearInterval(interval)
    }
  }, [controllerUrl, isResetView])

  useEffect(() => {
    setIsResetView(true)

    const resetTimer = window.setTimeout(() => {
      setHistory([])
      setSpeedHistory([])
      setTelemetry(EMPTY_TELEMETRY)
      setIsResetView(false)
    }, 2000)

    return () => {
      window.clearTimeout(resetTimer)
    }
  }, [resetTrigger])

  const isCenteredResetState =
    isResetView ||
    (history.length === 0 &&
      telemetry.robot_x === 0 &&
      telemetry.robot_y === 0 &&
      telemetry.target_x === 0 &&
      telemetry.target_y === 0)

  const mapBounds = useMemo(() => {
    const values = history.flatMap((point) => [point.x, point.y])
    values.push(telemetry.robot_x, telemetry.robot_y, telemetry.target_x, telemetry.target_y)

    const maxAbs = Math.max(100, ...values.map((value) => Math.abs(value)))
    const span = Math.max(1, maxAbs * 2)

    return { min: -maxAbs, max: maxAbs, span }
  }, [history, isCenteredResetState, telemetry])

  const mapToCanvas = (value: number) => ((value - mapBounds.min) / mapBounds.span) * 200

  const speedScaleMax = useMemo(() => {
    const maxAbs = speedHistory.reduce((acc, speed) => Math.max(acc, Math.abs(speed)), 1)
    return Math.max(10, maxAbs)
  }, [speedHistory])

  const formatTimestamp = (ts: number) => {
    if (!ts) return '—'
    // If timestamp looks like milliseconds (>1e12) use directly,
    // if it's in seconds (typical <1e11) convert to ms.
    const dateMs = ts > 1e12 ? ts : ts > 1e9 ? ts : ts * 1000
    const d = new Date(dateMs)
    return d.toLocaleString()
  }

  return (
    <div className="position-panel">
      <h2>Robot Position & Telemetry</h2>
      <div className={`position-status ${isConnected ? 'connected' : 'disconnected'}`}>
        {isConnected ? 'Live /position stream' : 'Waiting for /position stream'}
      </div>
      
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
                points={history.map((p) => `${Math.min(200, Math.max(0, mapToCanvas(p.x)))},${Math.min(200, Math.max(0, mapToCanvas(p.y)))}`).join(' ')}
                fill="none"
                stroke="#4CAF50"
                strokeWidth="1"
                opacity="0.5"
              />
            )}
            
            {/* Target position */}
            <g transform={`translate(${Math.min(200, Math.max(0, mapToCanvas(telemetry.target_x)))},${Math.min(200, Math.max(0, mapToCanvas(telemetry.target_y)))})`}>
              <circle cx="0" cy="0" r="4" fill="#d32f2f" opacity="0.9" />
              <circle cx="0" cy="0" r="7" fill="none" stroke="#d32f2f" strokeWidth="1" opacity="0.6" />
            </g>

            {/* Robot position + heading arrow */}
            <g transform={`translate(${Math.min(200, Math.max(0, mapToCanvas(telemetry.robot_x)))},${Math.min(200, Math.max(0, mapToCanvas(telemetry.robot_y)))}) rotate(${telemetry.robot_ang})`}>
              <circle cx="0" cy="0" r="5" fill="#2196F3" />
              <polygon points="10,0 -6,-5 -6,5" fill="#FF9800" opacity="0.95" />
            </g>
          </svg>
          <p className="map-label">Robot (blue) and Target (red) | Auto-scaled map</p>
        </div>

        <div className="position-stats">
          <div className="stat-item">
            <label>Timestamp</label>
            <div className="stat-value small">{formatTimestamp(telemetry.timestamp)}</div>
          </div>
          <div className="stat-item">
            <label>Robot X</label>
            <div className="stat-value">{telemetry.robot_x.toFixed(1)} mm</div>
          </div>
          <div className="stat-item">
            <label>Robot Y</label>
            <div className="stat-value">{telemetry.robot_y.toFixed(1)} mm</div>
          </div>
          <div className="stat-item">
            <label>Robot Angle</label>
            <div className="stat-value">{telemetry.robot_ang.toFixed(1)} deg</div>
          </div>
          <div className="stat-item">
            <label>Robot Ang Speed</label>
            <div className="stat-value">{telemetry.robot_ang_spd.toFixed(1)}</div>
          </div>
          <div className="stat-item">
            <label>Robot Lin Speed</label>
            <div className="stat-value">{telemetry.robot_lin_spd.toFixed(1)} mm/s</div>
          </div>
          <div className="stat-item">
            <label>Target X</label>
            <div className="stat-value">{telemetry.target_x.toFixed(1)} mm</div>
          </div>
          <div className="stat-item">
            <label>Target Y</label>
            <div className="stat-value">{telemetry.target_y.toFixed(1)} mm</div>
          </div>
          <div className="stat-item">
            <label>Target Angle</label>
            <div className="stat-value">{telemetry.target_ang.toFixed(1)} deg</div>
          </div>
          <div className="stat-item">
            <label>Target Lin Speed</label>
            <div className="stat-value">{telemetry.target_lin_spd.toFixed(1)} mm/s</div>
          </div>
          <div className="stat-item">
            <label>Trail Points</label>
            <div className="stat-value">{history.length}</div>
          </div>
          <div className="stat-item">
            <label>Encoder C1</label>
            <div className="stat-value">{telemetry.enc_c1}</div>
          </div>
          <div className="stat-item">
            <label>Encoder C2</label>
            <div className="stat-value">{telemetry.enc_c2}</div>
          </div>
        </div>
      </div>

      <div className="telemetry-graph">
        <h3>Robot Linear Speed History</h3>
        <svg viewBox="0 0 400 150" className="graph-canvas">
          {/* Grid lines */}
          <line x1="0" y1="25" x2="400" y2="25" stroke="#e0e0e0" strokeWidth="1" />
          <line x1="0" y1="75" x2="400" y2="75" stroke="#e0e0e0" strokeWidth="1" />
          <line x1="0" y1="125" x2="400" y2="125" stroke="#e0e0e0" strokeWidth="1" />
          
          {/* Speed line graph */}
          {speedHistory.length > 1 && (
            <polyline
              points={speedHistory.map((speed, i) => `${(i / Math.max(1, speedHistory.length - 1)) * 400},${75 - (speed / speedScaleMax) * 60}`).join(' ')}
              fill="none"
              stroke="#FF9800"
              strokeWidth="2"
            />
          )}
          
          {/* Axes */}
          <line x1="0" y1="0" x2="0" y2="150" stroke="#333" strokeWidth="1" />
          <line x1="0" y1="150" x2="400" y2="150" stroke="#333" strokeWidth="1" />
        </svg>
        <p className="graph-label">Speed scale: +/- {speedScaleMax.toFixed(1)} mm/s</p>
      </div>
    </div>
  )
}
