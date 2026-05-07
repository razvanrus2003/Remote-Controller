import { useState, useEffect, useMemo } from 'react'
import axios from 'axios'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import '../styles/RobotPosition.css'
import { controllerUrl } from '../config.ts'

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
  rpm1: number
  rpm2: number
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
  rpm1: 0,
  rpm2: 0,
}

export default function RobotPosition({ resetTrigger = 0 }: { resetTrigger?: number }) {
  const [telemetry, setTelemetry] = useState<PositionTelemetry>(EMPTY_TELEMETRY)
  const [history, setHistory] = useState<HistoryPoint[]>([])
  
  const [rpmHistory, setRpmHistory] = useState<Array<{ time: number; rpm1: number; rpm2: number }>>([])
  const [speedHistory, setSpeedHistory] = useState<Array<{ time: number; speed: number }>>([])
  const [rpmTargets, setRpmTargets] = useState<{ rpm1: number | null; rpm2: number | null }>({
    rpm1: null,
    rpm2: null,
  })
  const [isConnected, setIsConnected] = useState(false)
  const [lastRpmCommandTimestamp, setLastRpmCommandTimestamp] = useState<number | null>(null)
  const [isResetView, setIsResetView] = useState(false)

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
        key === 'enc_c2' ||
        key === 'rpm1' ||
        key === 'rpm2'
      ) {
        parsed[key] = numericValue
      }
    }

    // rpm1/rpm2 are optional in the string payload; default to 0 when missing
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

    // ensure rpm keys exist
    parsed.rpm1 = parsed.rpm1 === undefined ? 0 : parsed.rpm1
    parsed.rpm2 = parsed.rpm2 === undefined ? 0 : parsed.rpm2

    return parsed as PositionTelemetry
  }

  const parsePositionObject = (payload: Record<string, unknown>): PositionTelemetry | null => {
    const result: Partial<PositionTelemetry> = {}

    const requiredKeys: Array<keyof PositionTelemetry> = [
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

    let missingCount = 0
    for (const key of requiredKeys) {
      const raw = payload[key]
      if (typeof raw === 'number') {
        result[key] = raw
        continue
      }
      if (typeof raw === 'string') {
        const num = Number(raw)
        if (!Number.isNaN(num)) {
          result[key] = num
          continue
        }
      }
      // If missing or invalid, log it but allow with default value
      result[key] = 0
      missingCount++
      console.warn(`[RobotPosition] Missing or invalid required field: ${key}`)
    }

    // If too many fields are missing, it's probably the wrong data format
    if (missingCount > requiredKeys.length / 2) {
      console.error('[RobotPosition] More than half of required fields missing. Payload:', payload)
      return null
    }

    // rpm1/rpm2 are optional; accept numbers if present, otherwise default to 0
    const maybeRpm1 = payload['rpm1']
    const maybeRpm2 = payload['rpm2']
    const maybeRpmArr = payload['rpm']
    const parseMaybeNumber = (v: unknown) => {
      if (typeof v === 'number') return v
      if (typeof v === 'string') {
        const n = Number(v)
        return Number.isNaN(n) ? null : n
      }
      return null
    }

    const r1 = parseMaybeNumber(maybeRpm1)
    const r2 = parseMaybeNumber(maybeRpm2)

    if (r1 !== null && r2 !== null) {
      result.rpm1 = r1
      result.rpm2 = r2
    } else if (Array.isArray(maybeRpmArr) && maybeRpmArr.length >= 2) {
      const a0 = parseMaybeNumber(maybeRpmArr[0])
      const a1 = parseMaybeNumber(maybeRpmArr[1])
      result.rpm1 = a0 !== null ? a0 : 0
      result.rpm2 = a1 !== null ? a1 : 0
    } else {
      result.rpm1 = 0
      result.rpm2 = 0
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
          console.log('[RobotPosition] Parsing as string:', data)
          parsed = parsePositionString(data)
        } else if (typeof data === 'object' && data !== null) {
          const obj = data as Record<string, unknown>
          
          // Try nested structures first
          if (typeof obj.position === 'string') {
            console.log('[RobotPosition] Parsing nested position string:', obj.position)
            parsed = parsePositionString(obj.position)
          } else if (typeof obj.position === 'object' && obj.position !== null) {
            console.log('[RobotPosition] Parsing nested position object:', obj.position)
            parsed = parsePositionObject(obj.position as Record<string, unknown>)
          } else if (obj.data && typeof obj.data === 'object') {
            // Try obj.data wrapper
            console.log('[RobotPosition] Parsing obj.data:', obj.data)
            parsed = parsePositionObject(obj.data as Record<string, unknown>)
          } else {
            // Try direct object
            console.log('[RobotPosition] Parsing as direct object:', obj)
            parsed = parsePositionObject(obj)
          }
        }

        console.log('[RobotPosition] Parse result:', parsed)

        if (!isMounted) {
          console.log('[RobotPosition] Component unmounted, discarding data')
          return
        }

        if (!parsed) {
          console.warn('[RobotPosition] Failed to parse position data. Raw response:', data)
          setIsConnected(false)
          return
        }
        setTelemetry(parsed)
        setHistory((prev) => [
          ...prev.slice(-99),
          { x: parsed.robot_x, y: parsed.robot_y, timestamp: parsed.timestamp },
        ])
        // record rpm history (using telemetry timestamp)
        setRpmHistory((prev) => [...prev.slice(-239), { time: parsed.timestamp, rpm1: parsed.rpm1, rpm2: parsed.rpm2 }])
        // record linear speed history
        setSpeedHistory((prev) => [...prev.slice(-119), { time: parsed.timestamp, speed: parsed.robot_lin_spd }])
        setIsConnected(true)
      } catch (error) {
        console.error('Failed to fetch position data:', error)
        if (isMounted) {
          setIsConnected(false)
        }
      }
    }

    const debugFetch = async () => {
      try {
        const response = await axios.get(`${controllerUrl}/position`)
        console.log('[RobotPosition] API Response:', response.data)
        console.log('[RobotPosition] Response Type:', typeof response.data)
        console.log('[RobotPosition] Response Keys:', Object.keys(response.data || {}))
      } catch (err) {
        console.error('[RobotPosition] Debug fetch error:', err)
      }
    }

    // Log the first response for debugging
    void debugFetch()

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
    // initialize from localStorage
    try {
      const stored = localStorage.getItem('lastRpmCommandTimestamp')
      if (stored) setLastRpmCommandTimestamp(Number(stored))
    } catch {}

    try {
      const storedTargets = localStorage.getItem('rpmTargets')
      if (storedTargets) {
        const parsedTargets = JSON.parse(storedTargets) as { rpm1?: number; rpm2?: number }
        setRpmTargets({
          rpm1: typeof parsedTargets.rpm1 === 'number' ? parsedTargets.rpm1 : null,
          rpm2: typeof parsedTargets.rpm2 === 'number' ? parsedTargets.rpm2 : null,
        })
      }
    } catch {}

    const handler = (e: Event) => {
      try {
        const detail = (e as CustomEvent).detail as number
        if (typeof detail === 'number') setLastRpmCommandTimestamp(detail)
      } catch {}
    }

    const targetHandler = (e: Event) => {
      try {
        const detail = (e as CustomEvent).detail as { rpm1?: number; rpm2?: number } | null
        if (!detail) return
        setRpmTargets({
          rpm1: typeof detail.rpm1 === 'number' ? detail.rpm1 : null,
          rpm2: typeof detail.rpm2 === 'number' ? detail.rpm2 : null,
        })
      } catch {}
    }

    window.addEventListener('lastRpmCommand', handler as EventListener)
    window.addEventListener('rpmTargetsUpdated', targetHandler as EventListener)
    return () => {
      window.removeEventListener('lastRpmCommand', handler as EventListener)
      window.removeEventListener('rpmTargetsUpdated', targetHandler as EventListener)
    }
  }, [])

  useEffect(() => {
    setIsResetView(true)

    const resetTimer = window.setTimeout(() => {
      setHistory([])
      setRpmHistory([])
      setSpeedHistory([])
      setTelemetry(EMPTY_TELEMETRY)
      setRpmTargets({ rpm1: null, rpm2: null })
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
        {isConnected ? 'Live /position stream' : `Waiting for /position stream from ${controllerUrl}`}
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
          <div className="stat-item">
            <label>Motor RPM 1</label>
            <div className="stat-value">{telemetry.rpm1.toFixed(1)} RPM</div>
          </div>
          <div className="stat-item">
            <label>Motor RPM 2</label>
            <div className="stat-value">{telemetry.rpm2.toFixed(1)} RPM</div>
          </div>
        </div>
      </div>

      <div className="telemetry-graph">
        <h3>Motor RPM 1 (RPM)</h3>
        <div style={{ width: '100%', height: 180 }}>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={rpmHistory.map((d) => ({ time: d.time, rpm: d.rpm1 }))} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="time"
                tickFormatter={(t) => {
                  if (!t) return ''
                  const ms = t > 1e12 ? t : t > 1e9 ? t : t * 1000
                  const d = new Date(ms)
                  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
                }}
                />
              <YAxis label={{ value: 'RPM', angle: -90, position: 'insideLeft' }} />
              <Tooltip labelFormatter={(t) => formatTimestamp(Number(t))} />
              <Line type="monotone" dataKey="rpm" stroke="#8884d8" name="RPM 1" dot={false} isAnimationActive={false} />
              {rpmTargets.rpm1 !== null && (
                <ReferenceLine
                  y={rpmTargets.rpm1}
                  stroke="#00aa00"
                  strokeDasharray="5 5"
                  label={{ value: 'Target RPM 1', position: 'insideTopLeft', fill: '#00aa00' }}
                />
              )}
              {lastRpmCommandTimestamp !== null && (
                <ReferenceLine x={lastRpmCommandTimestamp} stroke="#00aa00" strokeDasharray="5 5" label={{ value: 'RPM Cmd', position: 'top', fill: '#00aa00' }} />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>

        <h3>Motor RPM 2 (RPM)</h3>
        <div style={{ width: '100%', height: 180 }}>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={rpmHistory.map((d) => ({ time: d.time, rpm: d.rpm2 }))} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="time"
                tickFormatter={(t) => {
                  if (!t) return ''
                  const ms = t > 1e12 ? t : t > 1e9 ? t : t * 1000
                  const d = new Date(ms)
                  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
                }}
                />
              <YAxis label={{ value: 'RPM', angle: -90, position: 'insideLeft' }} />
              <Tooltip labelFormatter={(t) => formatTimestamp(Number(t))} />
              <Line type="monotone" dataKey="rpm" stroke="#82ca9d" name="RPM 2" dot={false} isAnimationActive={false} />
              {rpmTargets.rpm2 !== null && (
                <ReferenceLine
                  y={rpmTargets.rpm2}
                  stroke="#00aa00"
                  strokeDasharray="5 5"
                  label={{ value: 'Target RPM 2', position: 'insideTopLeft', fill: '#00aa00' }}
                />
              )}
              {lastRpmCommandTimestamp !== null && (
                <ReferenceLine x={lastRpmCommandTimestamp} stroke="#00aa00" strokeDasharray="5 5" label={{ value: 'RPM Cmd', position: 'top', fill: '#00aa00' }} />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>

        <h3>Robot Linear Speed (mm/s)</h3>
        <div style={{ width: '100%', height: 200 }}>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={speedHistory.map((d) => ({ time: d.time, speed: d.speed }))} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="time"
                tickFormatter={(t) => {
                  if (!t) return ''
                  const ms = t > 1e12 ? t : t > 1e9 ? t : t * 1000
                  const d = new Date(ms)
                  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
                }}
                />
              <YAxis label={{ value: 'mm/s', angle: -90, position: 'insideLeft' }} />
              <Tooltip labelFormatter={(t) => formatTimestamp(Number(t))} formatter={(value) => `${Number(value).toFixed(1)} mm/s`} />
              <Line type="monotone" dataKey="speed" stroke="#FF9800" name="Linear Speed" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p className="graph-label">Shows last {rpmHistory.length} RPM samples and {speedHistory.length} speed samples</p>
      </div>
    </div>
  )
}
