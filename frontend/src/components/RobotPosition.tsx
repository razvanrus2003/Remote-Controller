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
  target_x: number
  target_y: number
  target_ang: number
  target_rpm1: number
  target_rpm2: number
  enc_c1: number
  enc_c2: number
  e1clk: number
  e1dt: number
  e2clk: number
  e2dt: number
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
  target_x: 0,
  target_y: 0,
  target_ang: 0,
  target_rpm1: 0,
  target_rpm2: 0,
  enc_c1: 0,
  enc_c2: 0,
  e1clk: 0,
  e1dt: 0,
  e2clk: 0,
  e2dt: 0,
  rpm1: 0,
  rpm2: 0,
}

export default function RobotPosition({ resetTrigger = 0 }: { resetTrigger?: number }) {
  const [telemetry, setTelemetry] = useState<PositionTelemetry>(EMPTY_TELEMETRY)
  const [history, setHistory] = useState<HistoryPoint[]>([])
  
  const [rpmHistory, setRpmHistory] = useState<Array<{ time: number; rpm1: number; rpm2: number }>>([])
  const [pinsHistory, setPinsHistory] = useState<Array<{ time: number; e1CLK: number; e1DT: number; e2CLK: number; e2DT: number }>>([])
  const [rpmTargets, setRpmTargets] = useState<{ rpm1: number | null; rpm2: number | null }>({
    rpm1: null,
    rpm2: null,
  })
  const [isConnected, setIsConnected] = useState(false)
  const [lastRpmCommandTimestamp, setLastRpmCommandTimestamp] = useState<number | null>(null)
  const [isResetView, setIsResetView] = useState(false)

  const normalizeTimestamp = (timestamp: number | undefined) => {
    if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= 0) {
      return 0
    }

    const absoluteTimestamp = Math.abs(timestamp)

    // Support microseconds, milliseconds, and seconds.
    if (absoluteTimestamp >= 1e15) {
      return Math.round(timestamp / 1000)
    }

    if (absoluteTimestamp >= 1e12) {
      return Math.round(timestamp)
    }

    return Math.round(timestamp * 1000)
  }

  const parseMaybeNumber = (value: unknown) => {
    if (typeof value === 'number') return value
    if (typeof value === 'string') {
      const num = Number(value)
      return Number.isNaN(num) ? null : num
    }
    return null
  }

  const parseStringSection = (payload: string, pattern: RegExp) => {
    const match = payload.match(pattern)
    if (!match) return null

    const values = match.slice(1).map((value) => Number(value))
    return values.every((value) => Number.isFinite(value)) ? values : null
  }

  const parsePositionString = (payload: string): PositionTelemetry | null => {
    const parsed: Record<string, unknown> = {}

    // Accept flat `key=value` telemetry with commas, pipes, or spaces between pairs.
    const keyValueRegex = /([a-zA-Z0-9_]+)=([^\s,|]+)/g
    let match: RegExpExecArray | null
    while ((match = keyValueRegex.exec(payload)) !== null) {
      const key = match[1]
      const value = parseMaybeNumber(match[2])
      if (value !== null) {
        parsed[key] = value
      }
    }

    // Support the older sectioned format as a fallback.
    if (Object.keys(parsed).length === 0) {
      const robot = parseStringSection(payload, /ROBOT\s+x=([^\s|]+)\s+y=([^\s|]+)\s+ang=([^\s|]+)/i)
      const target = parseStringSection(payload, /TARGET\s+x=([^\s|]+)\s+y=([^\s|]+)\s+ang=([^\s|]+)\s+rpm1=([^\s|]+)\s+rpm2=([^\s|]+)/i)
      const enc = parseStringSection(payload, /ENC\s+c1=([^\s|]+)\s+c2=([^\s|]+)/i)
      const pins = parseStringSection(payload, /PINS\s+e1clk=([^\s|]+)\s+e1dt=([^\s|]+)\s+e2clk=([^\s|]+)\s+e2dt=([^\s|]+)/i)
      const rpmMatch = parseStringSection(payload, /RPM\s+m1=([^\s|]+)\s+m2=([^\s|]+)/i)

      if (!robot || !target || !enc || !pins || !rpmMatch) {
        return null
      }

      parsed.robot_x = robot[0]
      parsed.robot_y = robot[1]
      parsed.robot_ang = robot[2]
      parsed.target_x = target[0]
      parsed.target_y = target[1]
      parsed.target_ang = target[2]
      parsed.target_rpm1 = target[3]
      parsed.target_rpm2 = target[4]
      parsed.enc_c1 = enc[0]
      parsed.enc_c2 = enc[1]
      parsed.e1clk = pins[0]
      parsed.e1dt = pins[1]
      parsed.e2clk = pins[2]
      parsed.e2dt = pins[3]
      parsed.rpm1 = rpmMatch[0]
      parsed.rpm2 = rpmMatch[1]
    }

    return parsePositionObject(parsed)
  }

  const parsePositionObject = (payload: Record<string, unknown>): PositionTelemetry | null => {
    const result: Partial<PositionTelemetry> = {}

    const getField = (...keys: string[]) => {
      for (const key of keys) {
        const parsed = parseMaybeNumber(payload[key])
        if (parsed !== null) return parsed
      }
      return null
    }

    const requiredFields: Array<[keyof PositionTelemetry, string[]]> = [
      ['robot_x', ['robot_x', 'x']],
      ['robot_y', ['robot_y', 'y']],
      ['robot_ang', ['robot_ang', 'ang', 'theta']],
      ['target_x', ['target_x']],
      ['target_y', ['target_y']],
      ['target_ang', ['target_ang', 'target_heading']],
      ['target_rpm1', ['target_rpm1']],
      ['target_rpm2', ['target_rpm2']],
      ['enc_c1', ['enc_c1', 'c1']],
      ['enc_c2', ['enc_c2', 'c2']],
      ['rpm1', ['rpm1']],
      ['rpm2', ['rpm2']],
    ]

    let missingCount = 0
    for (const [key, aliases] of requiredFields) {
      const value = getField(...aliases)
      if (value !== null) {
        result[key] = value
        continue
      }
      result[key] = 0
      missingCount++
      console.warn(`[RobotPosition] Missing or invalid required field: ${key}`)
    }

    // Timestamp is optional in the compact payload; fall back to receive time.
    const timestamp = getField('timestamp', 'ts', 'time')
    result.timestamp = timestamp !== null ? normalizeTimestamp(timestamp) : normalizeTimestamp(Date.now())

    // If too many fields are missing, it's probably the wrong data format.
    if (missingCount > requiredFields.length / 2) {
      console.error('[RobotPosition] More than half of required fields missing. Payload:', payload)
      return null
    }

    result.rpm1 = getField('rpm1', 'm1') ?? 0
    result.rpm2 = getField('rpm2', 'm2') ?? 0

    // parse pin values if present at top-level or under a 'pins' object
    const getPin = (key: string) => {
      const top = parseMaybeNumber(payload[key])
      if (top !== null) return top
      const pinsObj = (payload['pins'] || payload['PINS']) as Record<string, unknown> | undefined
      if (pinsObj && typeof pinsObj === 'object') {
        const v = parseMaybeNumber(pinsObj[key])
        if (v !== null) return v
      }
      return 0
    }

    result.e1clk = getPin('e1clk')
    result.e1dt = getPin('e1dt')
    result.e2clk = getPin('e2clk')
    result.e2dt = getPin('e2dt')

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
        // record encoder pin history (keep recent samples only)
        setPinsHistory((prev) => [...prev.slice(-20), { time: parsed.timestamp, e1CLK: parsed.e1clk, e1DT: parsed.e1dt, e2CLK: parsed.e2clk, e2DT: parsed.e2dt }])
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
    }, 100)

    return () => {
      isMounted = false
      window.clearInterval(interval)
    }
  }, [controllerUrl, isResetView])

  useEffect(() => {
    // initialize from localStorage
    try {
      const stored = localStorage.getItem('lastRpmCommandTimestamp')
      if (stored) setLastRpmCommandTimestamp(normalizeTimestamp(Number(stored)))
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
        if (typeof detail === 'number') setLastRpmCommandTimestamp(normalizeTimestamp(detail))
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
      setRpmTargets({ rpm1: null, rpm2: null })
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
    const d = new Date(ts)
    return d.toLocaleString()
  }

  const formatClockTime = (ts: number) => {
    if (!ts) return ''
    const d = new Date(ts)
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
  }

  const exportCsv = (rows: Array<Array<string | number>>, filename: string) => {
    const escape = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`
    const csv = rows.map((r) => r.map(escape).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  const handleDownloadRpm1 = () => {
    const rows: Array<Array<string | number>> = [["timestamp_ms", "timestamp_iso", "rpm"]]
    rpmHistory.forEach((d) => rows.push([d.time, new Date(d.time).toISOString(), d.rpm1]))
    exportCsv(rows, `motor1_rpm_${Date.now()}.csv`)
  }

  const handleDownloadRpm2 = () => {
    const rows: Array<Array<string | number>> = [["timestamp_ms", "timestamp_iso", "rpm"]]
    rpmHistory.forEach((d) => rows.push([d.time, new Date(d.time).toISOString(), d.rpm2]))
    exportCsv(rows, `motor2_rpm_${Date.now()}.csv`)
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

        <h3>Encoder 1 Pins (CLK / DT)</h3>
        <div style={{ width: '100%', height: 140 }}>
          <ResponsiveContainer width="100%" height={120}>
            <LineChart data={pinsHistory.map((d) => ({ time: d.time, clk: d.e1CLK, dt: d.e1DT + 2 }))} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="time" tickFormatter={(t) => formatClockTime(Number(t))} />
              <YAxis domain={[0, 1]} tickCount={2} allowDecimals={false} />
              <Tooltip labelFormatter={(t) => formatTimestamp(Number(t))} formatter={(v) => Number(v).toFixed(0)} />
              <Line type="stepAfter" dataKey="clk" stroke="#1976d2" name="CLK" dot={false} isAnimationActive={false} />
              <Line type="stepAfter" dataKey="dt" stroke="#ef6c00" name="DT" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <h3>Encoder 2 Pins (CLK / DT)</h3>
        <div style={{ width: '100%', height: 140 }}>
          <ResponsiveContainer width="100%" height={120}>
            <LineChart data={pinsHistory.map((d) => ({ time: d.time, clk: d.e2CLK, dt: d.e2DT + 2 }))} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="time" tickFormatter={(t) => formatClockTime(Number(t))} />
              <YAxis domain={[0, 1]} tickCount={2} allowDecimals={false} />
              <Tooltip labelFormatter={(t) => formatTimestamp(Number(t))} formatter={(v) => Number(v).toFixed(0)} />
              <Line type="stepAfter" dataKey="clk" stroke="#1976d2" name="CLK" dot={false} isAnimationActive={false} />
              <Line type="stepAfter" dataKey="dt" stroke="#ef6c00" name="DT" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
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
            <label>Target RPM 1</label>
            <div className="stat-value">{telemetry.target_rpm1.toFixed(1)}</div>
          </div>
          <div className="stat-item">
            <label>Target RPM 2</label>
            <div className="stat-value">{telemetry.target_rpm2.toFixed(1)}</div>
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
        <div className="graph-header">
          <h3>Motor RPM 1 (RPM)</h3>
          <button onClick={handleDownloadRpm1} className="download-btn">Download CSV</button>
        </div>
        <div style={{ width: '100%', height: 180 }}>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={rpmHistory.map((d) => ({ time: d.time, rpm: d.rpm1 }))} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="time"
                tickFormatter={(t) => formatClockTime(Number(t))}
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

        <div className="graph-header">
          <h3>Motor RPM 2 (RPM)</h3>
          <button onClick={handleDownloadRpm2} className="download-btn">Download CSV</button>
        </div>
        <div style={{ width: '100%', height: 180 }}>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={rpmHistory.map((d) => ({ time: d.time, rpm: d.rpm2 }))} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="time"
                tickFormatter={(t) => formatClockTime(Number(t))}
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

        <p className="graph-label">Shows the most recent RPM samples and target overlays.</p>
      </div>
    </div>
  )
}
