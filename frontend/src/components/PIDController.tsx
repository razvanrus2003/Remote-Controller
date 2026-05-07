import { useState } from 'react'
import axios from 'axios'
import '../styles/PIDController.css'
import { controllerUrl } from '../config.ts'

interface PIDValues {
  kp: number
  ki: number
  kd: number
}

interface ControllerConfig {
  S: PIDValues
  P: PIDValues
  H: PIDValues
  A: PIDValues
}

const DEFAULT_CONFIG: ControllerConfig = {
  S: { kp: 0, ki: 0, kd: 0 },
  P: { kp: 0, ki: 0, kd: 0 },
  H: { kp: 0, ki: 0, kd: 0 },
  A: { kp: 0, ki: 0, kd: 0 },
}

export default function PIDController() {
  const [editingConfig, setEditingConfig] = useState<ControllerConfig>(DEFAULT_CONFIG)
  const [currentConfig, setCurrentConfig] = useState<ControllerConfig>(DEFAULT_CONFIG)
  const [activeController, setActiveController] = useState<'S' | 'P' | 'H' | 'A'>('S')
  const [isLoading, setIsLoading] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const controllers: Array<{ key: 'S' | 'P' | 'H' | 'A'; label: string }> = [
    { key: 'S', label: 'Speed (S)' },
    { key: 'P', label: 'Position (P)' },
    { key: 'H', label: 'Heading (H)' },
    { key: 'A', label: 'Arm (A)' },
  ]

  const handleValueChange = (field: keyof PIDValues, value: string) => {
    const numValue = value === '' ? 0 : parseFloat(value) || 0
    setEditingConfig((prev) => ({
      ...prev,
      [activeController]: {
        ...prev[activeController],
        [field]: numValue,
      },
    }))
  }

  const handleSubmit = async () => {
    if (!activeController) return

    setIsLoading(true)
    setMessage(null)

    try {
      const pidValues = [
        editingConfig[activeController].kp,
        editingConfig[activeController].ki,
        editingConfig[activeController].kd,
      ]

      const response = await axios.post(
        `${controllerUrl}/command/pid/${activeController}`,
        pidValues,
        { headers: { 'Content-Type': 'application/json' } }
      )

      // Update current config only on successful apply
      setCurrentConfig((prev) => ({
        ...prev,
        [activeController]: { ...editingConfig[activeController] },
      }))

      setMessage({
        type: 'success',
        text: `PID values sent to ${controllers.find((c) => c.key === activeController)?.label || activeController}`,
      })
      console.log('[PIDController] Response:', response.data)
    } catch (error) {
      console.error('[PIDController] Failed to update PID:', error)
      setMessage({
        type: 'error',
        text: `Failed to update PID: ${error instanceof Error ? error.message : 'Unknown error'}`,
      })
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="pid-controller-panel">
      <h2>PID Controller Configuration</h2>

      {/* Controller Selection */}
      <div className="controller-tabs">
        {controllers.map(({ key, label }) => (
          <button
            key={key}
            className={`tab-button ${activeController === key ? 'active' : ''}`}
            onClick={() => {
              setActiveController(key)
              setMessage(null)
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* PID Values */}
      <div className="pid-form">
        <div className="pid-input-group">
          <label htmlFor="kp">KP (Proportional)</label>
          <input
            id="kp"
            type="number"
            step="0.01"
            value={editingConfig[activeController].kp || ''}
            placeholder="0"
            onChange={(e) => handleValueChange('kp', e.target.value)}
            disabled={isLoading}
          />
        </div>

        <div className="pid-input-group">
          <label htmlFor="ki">KI (Integral)</label>
          <input
            id="ki"
            type="number"
            step="0.01"
            value={editingConfig[activeController].ki || ''}
            placeholder="0"
            onChange={(e) => handleValueChange('ki', e.target.value)}
            disabled={isLoading}
          />
        </div>

        <div className="pid-input-group">
          <label htmlFor="kd">KD (Derivative)</label>
          <input
            id="kd"
            type="number"
            step="0.01"
            value={editingConfig[activeController].kd || ''}
            placeholder="0"
            onChange={(e) => handleValueChange('kd', e.target.value)}
            disabled={isLoading}
          />
        </div>
      </div>

      {/* Status Message */}
      {message && (
        <div className={`status-message ${message.type}`}>
          {message.type === 'success' ? '✓' : '✕'} {message.text}
        </div>
      )}

      {/* Action Buttons */}
      <div className="pid-actions">
        <button className="btn btn-submit" onClick={handleSubmit} disabled={isLoading}>
          {isLoading ? 'Sending...' : 'Apply PID Values'}
        </button>
      </div>

      {/* Current Values Display */}
      <div className="pid-summary">
        <h3>Current Configuration</h3>
        <div className="summary-grid">
          {controllers.map(({ key, label }) => (
            <div key={key} className="summary-item">
              <div className="summary-label">{label}</div>
              <div className="summary-values">
                KP: {currentConfig[key].kp.toFixed(2)} | KI: {currentConfig[key].ki.toFixed(2)} | KD: {currentConfig[key].kd.toFixed(2)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
