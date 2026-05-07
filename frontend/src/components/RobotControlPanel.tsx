import { useState, useCallback } from 'react'
import axios from 'axios'
import VideoFeed from './VideoFeed'
import '../styles/RobotControlPanel.css'

interface MotorCommand {
  motor_id: number
  power: number
}

interface TargetValues {
  speed_motor1: number
  speed_motor2: number
  position_x: number
  position_y: number
  heading: number
}

export default function RobotControlPanel({ onReset }: { onReset?: () => void } = {}) {
  const [motors, setMotors] = useState<MotorCommand[]>([
    { motor_id: 1, power: 0 },
    { motor_id: 2, power: 0 },
  ])

  const [targets, setTargets] = useState<TargetValues>({
    speed_motor1: 0,
    speed_motor2: 0,
    position_x: 0,
    position_y: 0,
    heading: 0,
  })

  const [isLoading, setIsLoading] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const controllerUrl = 'http://localhost:5000'

  const handleMotorChange = (motorId: number, newPower: number) => {
    setMotors(motors.map(m => 
      m.motor_id === motorId ? { ...m, power: Math.max(-100, Math.min(100, newPower)) } : m
    ))
  }

  const handleTargetChange = (field: keyof TargetValues, value: string) => {
    const numValue = value === '' ? 0 : parseFloat(value) || 0
    setTargets((prev) => ({
      ...prev,
      [field]: numValue,
    }))
  }

  const handleTargetSubmit = async (targetType: keyof TargetValues) => {
    setIsLoading(true)
    setMessage(null)

    try {
      let endpoint = ''
      let payload: any = null

      if (targetType === 'speed_motor1' || targetType === 'speed_motor2') {
        endpoint = '/command/rpm'
        payload = [targets.speed_motor1, targets.speed_motor2]
      } else if (targetType === 'position_x' || targetType === 'position_y') {
        endpoint = '/command/position'
        payload = [targets.position_x, targets.position_y]
      } else if (targetType === 'heading') {
        endpoint = '/command/angle'
        payload = [targets.heading]
      }

      const response = await axios.post(
        `${controllerUrl}${endpoint}`,
        payload,
        { headers: { 'Content-Type': 'application/json' } }
      )

      if (endpoint === '/command/rpm') {
        const rpmTargets = {
          rpm1: targets.speed_motor1,
          rpm2: targets.speed_motor2,
        }
        localStorage.setItem('rpmTargets', JSON.stringify(rpmTargets))
        window.dispatchEvent(new CustomEvent('rpmTargetsUpdated', { detail: rpmTargets }))
      }

      setMessage({
        type: 'success',
        text: `${targetType} set successfully`,
      })
      console.log('[RobotControlPanel] Target Response:', response.data)
    } catch (error) {
      console.error('[RobotControlPanel] Failed to set target:', error)
      setMessage({
        type: 'error',
        text: `Failed to set target: ${error instanceof Error ? error.message : 'Unknown error'}`,
      })
    } finally {
      setIsLoading(false)
    }
  }

  const sendMotorCommand = useCallback(async () => {
    setIsLoading(true)
    setMessage(null)

    try {
      // Normalize motor powers from -100..100 to -1.0..1.0
      const normalizedPowers = motors.map(m => m.power / 100)
      const response = await axios.post(
        `${controllerUrl}/command/power`,
        normalizedPowers,
        { headers: { 'Content-Type': 'application/json' } }
      )
      
      setMessage({
        type: 'success',
        text: 'Motor command sent',
      })
      console.log('[RobotControlPanel] Command sent:', response.data)
    } catch (error) {
      console.error('[RobotControlPanel] Failed to send command:', error)
      setMessage({
        type: 'error',
        text: `Failed to send command: ${error instanceof Error ? error.message : 'Unknown error'}`,
      })
    } finally {
      setIsLoading(false)
    }
  }, [motors])

  const resetAllMotors = () => {
    setMotors(motors.map(m => ({ ...m, power: 0 })))
  }

  const setMaxPower = () => {
    setMotors(motors.map(m => ({ ...m, power: 100 })))
  }

  const resetAllTargets = async () => {
    setIsLoading(true)
    setMessage(null)

    try {
      const response = await axios.post(
        `${controllerUrl}/command/reset`,
        {},
        { headers: { 'Content-Type': 'application/json' } }
      )

      setTargets({
        speed_motor1: 0,
        speed_motor2: 0,
        position_x: 0,
        position_y: 0,
        heading: 0,
      })

      localStorage.removeItem('rpmTargets')
      window.dispatchEvent(new CustomEvent('rpmTargetsUpdated', { detail: null }))

      setMessage({
        type: 'success',
        text: 'All targets reset',
      })
      console.log('[RobotControlPanel] Reset Response:', response.data)
      
      // Trigger graph reset
      onReset?.()
    } catch (error) {
      console.error('[RobotControlPanel] Failed to reset targets:', error)
      setMessage({
        type: 'error',
        text: `Failed to reset: ${error instanceof Error ? error.message : 'Unknown error'}`,
      })
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="control-panel-simple">
      <div className="panel-header">
        <h2>Motor Control</h2>
      </div>

      <div className="motors-grid">
        {motors.map((motor) => (
          <div key={motor.motor_id} className="motor-control">
            <h3>Motor {motor.motor_id}</h3>
            
            <div className="power-display">
              <span className={`power-value ${motor.power > 0 ? 'forward' : motor.power < 0 ? 'backward' : ''}`}>
                {motor.power}%
              </span>
            </div>

            <input
              type="range"
              min="-100"
              max="100"
              value={motor.power}
              onChange={(e) => handleMotorChange(motor.motor_id, Number(e.target.value))}
              className="slider"
              style={{
                background: motor.power > 0 
                  ? `linear-gradient(to right, #e0e0e0 0%, #4CAF50 ${motor.power}%, #e0e0e0 ${motor.power}%, #e0e0e0 100%)`
                  : motor.power < 0
                  ? `linear-gradient(to right, #e0e0e0 0%, #e0e0e0 ${100 + motor.power}%, #FF6B6B ${100 + motor.power}%, #e0e0e0 100%)`
                  : '#e0e0e0'
              }}
            />

            <div className="motor-buttons">
              <button 
                onClick={() => handleMotorChange(motor.motor_id, 0)}
                className="btn btn-small btn-neutral"
              >
                Stop
              </button>
              <button 
                onClick={() => handleMotorChange(motor.motor_id, 50)}
                className="btn btn-small btn-primary"
              >
                Half
              </button>
              <button 
                onClick={() => handleMotorChange(motor.motor_id, 100)}
                className="btn btn-small btn-success"
              >
                Max
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="control-actions">
        <button onClick={resetAllMotors} className="btn btn-danger">
          Reset All
        </button>
        <button onClick={setMaxPower} className="btn btn-success">
          Max All
        </button>
        <button onClick={sendMotorCommand} className="btn btn-primary btn-send">
          Send Command
        </button>
      </div>

      {/* Status Message */}
      {message && (
        <div className={`status-message ${message.type}`}>
          {message.type === 'success' ? '✓' : '✕'} {message.text}
        </div>
      )}

      {/* Target Values Section */}
      <div className="target-values-section">
        <h3>Target Values</h3>
        
        <div className="target-controls">
          <div className="target-control">
            <div className="target-input-group">
              <label htmlFor="target-speed-m1">Target Speed Motor 1 (mm/s)</label>
              <input
                id="target-speed-m1"
                type="number"
                step="0.1"
                value={targets.speed_motor1 || ''}
                onChange={(e) => handleTargetChange('speed_motor1', e.target.value)}
                disabled={isLoading}
                placeholder="0"
              />
            </div>
            <button 
              className="btn btn-target" 
              onClick={() => handleTargetSubmit('speed_motor1')} 
              disabled={isLoading}
            >
              Send
            </button>
          </div>

          <div className="target-control">
            <div className="target-input-group">
              <label htmlFor="target-speed-m2">Target Speed Motor 2 (mm/s)</label>
              <input
                id="target-speed-m2"
                type="number"
                step="0.1"
                value={targets.speed_motor2 || ''}
                onChange={(e) => handleTargetChange('speed_motor2', e.target.value)}
                disabled={isLoading}
                placeholder="0"
              />
            </div>
            <button 
              className="btn btn-target" 
              onClick={() => handleTargetSubmit('speed_motor2')} 
              disabled={isLoading}
            >
              Send
            </button>
          </div>

          <div className="target-control">
            <div className="target-input-group">
              <label htmlFor="target-pos-x">Target Position X (mm)</label>
              <input
                id="target-pos-x"
                type="number"
                step="1"
                value={targets.position_x || ''}
                onChange={(e) => handleTargetChange('position_x', e.target.value)}
                disabled={isLoading}
                placeholder="0"
              />
            </div>
            <button 
              className="btn btn-target" 
              onClick={() => handleTargetSubmit('position_x')} 
              disabled={isLoading}
            >
              Send
            </button>
          </div>

          <div className="target-control">
            <div className="target-input-group">
              <label htmlFor="target-pos-y">Target Position Y (mm)</label>
              <input
                id="target-pos-y"
                type="number"
                step="1"
                value={targets.position_y || ''}
                onChange={(e) => handleTargetChange('position_y', e.target.value)}
                disabled={isLoading}
                placeholder="0"
              />
            </div>
            <button 
              className="btn btn-target" 
              onClick={() => handleTargetSubmit('position_y')} 
              disabled={isLoading}
            >
              Send
            </button>
          </div>

          <div className="target-control">
            <div className="target-input-group">
              <label htmlFor="target-heading">Target Heading (deg)</label>
              <input
                id="target-heading"
                type="number"
                step="0.1"
                value={targets.heading || ''}
                onChange={(e) => handleTargetChange('heading', e.target.value)}
                disabled={isLoading}
                placeholder="0"
              />
            </div>
            <button 
              className="btn btn-target" 
              onClick={() => handleTargetSubmit('heading')} 
              disabled={isLoading}
            >
              Send
            </button>
          </div>
        </div>

        <button 
          className="btn btn-target-reset" 
          onClick={resetAllTargets} 
          disabled={isLoading}
        >
          Reset
        </button>
      </div>

      <VideoFeed controllerUrl={controllerUrl} />
    </div>
  )
}
