import { useState, useCallback, useEffect } from 'react'
import axios from 'axios'
import './App.css'
import RobotControlPanel from './components/RobotControlPanel'
import RobotPosition from './components/RobotPosition'
import HealthDashboard from './components/HealthDashboard'
import PIDController from './components/PIDController'
import { controllerUrl } from './config.ts'

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

function App() {
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'disconnected'>('disconnected')
  const [healthStats, setHealthStats] = useState<HealthStats | null>(null)
  const [healthHistory, setHealthHistory] = useState<HealthStats[]>([])
  const [resetTrigger, setResetTrigger] = useState<number>(0)

  const handleReset = useCallback(() => {
    setResetTrigger((prev) => prev + 1)
  }, [])

  const parseMetricNumber = (value: string): number | null => {
    const cleaned = value.trim().replace(/[%A-Za-z]+$/g, '')
    const match = cleaned.match(/-?\d+(?:\.\d+)?/)
    if (!match) {
      return null
    }

    const parsedNumber = Number(match[0])
    return Number.isNaN(parsedNumber) ? null : parsedNumber
  }

  const parseMetricsString = (payload: string): HealthStats | null => {
    const parts = payload.split(',').map((part) => part.trim())
    const parsed: Partial<HealthStats> = {}

    for (const part of parts) {
      const [key, value] = part.split('=').map((item) => item.trim())
      if (!key || value === undefined) {
        continue
      }

      const numValue = parseMetricNumber(value)
      if (numValue === null) {
        continue
      }

      if (
        key === 'cpu_percent' ||
        key === 'mem_used_mb' ||
        key === 'mem_total_mb' ||
        key === 'mem_available_mb' ||
        key === 'swap_used_mb' ||
        key === 'swap_free_mb' ||
        key === 'swap_total_mb' ||
        key === 'period_sec'
      ) {
        parsed[key] = numValue
      }
    }

    if (
      parsed.cpu_percent === undefined ||
      parsed.mem_used_mb === undefined ||
      parsed.mem_total_mb === undefined ||
      parsed.mem_available_mb === undefined ||
      parsed.swap_used_mb === undefined ||
      parsed.swap_free_mb === undefined ||
      parsed.swap_total_mb === undefined ||
      parsed.period_sec === undefined
    ) {
      return null
    }

    return parsed as HealthStats
  }

  const parseMetricsObject = (payload: Partial<HealthStats>): HealthStats | null => {
    if (
      typeof payload.cpu_percent !== 'number' ||
      typeof payload.mem_used_mb !== 'number' ||
      typeof payload.mem_total_mb !== 'number' ||
      typeof payload.mem_available_mb !== 'number' ||
      typeof payload.swap_used_mb !== 'number' ||
      typeof payload.swap_free_mb !== 'number' ||
      typeof payload.swap_total_mb !== 'number' ||
      typeof payload.period_sec !== 'number'
    ) {
      return null
    }

    return {
      cpu_percent: payload.cpu_percent,
      mem_used_mb: payload.mem_used_mb,
      mem_total_mb: payload.mem_total_mb,
      mem_available_mb: payload.mem_available_mb,
      swap_used_mb: payload.swap_used_mb,
      swap_free_mb: payload.swap_free_mb,
      swap_total_mb: payload.swap_total_mb,
      period_sec: payload.period_sec,
    }
  }

  const fetchHealthStats = useCallback(async () => {
    try {
      const response = await axios.get(`${controllerUrl}/health`)
      const data = response.data as unknown

      let parsed: HealthStats | null = null

      if (typeof data === 'object' && data !== null) {
        const obj = data as Record<string, unknown>
        if (typeof obj.health === 'string') {
          parsed = parseMetricsString(obj.health)
        } else if (typeof obj.health === 'object' && obj.health !== null) {
          parsed = parseMetricsObject(obj.health as Partial<HealthStats>)
        } else {
          parsed = parseMetricsObject(obj as Partial<HealthStats>)
        }

        const statusStr = typeof obj.status === 'string' ? obj.status.toLowerCase() : ''
        const isHealthy = statusStr === 'healthy' && parsed !== null

        setConnectionStatus(isHealthy ? 'connected' : 'disconnected')
        if (parsed) {
          setHealthStats(parsed)
          setHealthHistory((prev) => [...prev.slice(-59), parsed] as HealthStats[])
        }
      }
    } catch (error) {
      console.error('Health check failed:', error)
      setConnectionStatus('disconnected')
    }
  }, [])

  useEffect(() => {
    void fetchHealthStats()
  }, [fetchHealthStats])

  useEffect(() => {
    if (!connectionStatus) {
      const reconnectInterval = window.setInterval(() => {
        void fetchHealthStats()
      }, 2000)
      return () => window.clearInterval(reconnectInterval)
    }

    const intervalId = window.setInterval(() => {
      void fetchHealthStats()
    }, 1000)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [connectionStatus, fetchHealthStats])

  const RobotControlPanelAny = RobotControlPanel as any

  return (
    <div className="app">
      <header className="app-header">
        <h1>🤖 Robot Control Interface</h1>
        <div className={`status-indicator ${connectionStatus}`}>
          <div className="status-dot"></div>
          <span>{connectionStatus === 'connected' ? 'Connected' : 'Disconnected'}</span>
        </div>
      </header>

      <main className="app-main">
        <div className="control-section">
          <RobotControlPanelAny onReset={handleReset} />
        </div>

        <div className="pid-section">
          <PIDController />
        </div>

        <div className="visualization-grid">
          <RobotPosition resetTrigger={resetTrigger} />
          <HealthDashboard healthStats={healthStats} healthHistory={healthHistory} isConnected={connectionStatus === 'connected'} />
        </div>
      </main>
    </div>
  )
}

export default App
