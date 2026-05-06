import { useState, useCallback } from 'react'
import axios from 'axios'
import VideoFeed from './VideoFeed'
import '../styles/RobotControlPanel.css'

interface RobotControlPanelProps {
  onReset?: () => void
}

export default function RobotControlPanel({ onReset }: RobotControlPanelProps) {
  const [motorPower, setMotorPower] = useState<[number, number]>([0, 0])
  const [targetRpm, setTargetRpm] = useState<[number | string, number | string]>([0, 0])
  const [targetPosition, setTargetPosition] = useState<[number | string, number | string]>([0, 0])
  const [targetAngle, setTargetAngle] = useState<number | string>(0)

  const controllerUrl = 'http://192.168.1.132:5000'

  const clampMotorPower = (value: number) => Math.max(-1, Math.min(1, value))

  const handleMotorPowerChange = (index: 0 | 1, value: number) => {
    setMotorPower((prev) => {
      const next: [number, number] = [...prev] as [number, number]
      next[index] = clampMotorPower(value)
      return next
    })
  }

  const sendMotorPower = useCallback(async () => {
    try {
      const response = await axios.post(`${controllerUrl}/command/power`, motorPower)
      console.log('Motor power sent:', response.data)
    } catch (error) {
      console.error('Failed to send motor power:', error)
    }
  }, [controllerUrl, motorPower])

  const sendTargetRpm = useCallback(async () => {
    try {
      const rpmValues: [number, number] = [
        typeof targetRpm[0] === 'string' ? (targetRpm[0] === '' ? 0 : Number(targetRpm[0])) : targetRpm[0],
        typeof targetRpm[1] === 'string' ? (targetRpm[1] === '' ? 0 : Number(targetRpm[1])) : targetRpm[1],
      ]
      const response = await axios.post(`${controllerUrl}/command/rpm`, rpmValues)
      console.log('Target RPM sent:', response.data)
    } catch (error) {
      console.error('Failed to send target RPM:', error)
    }
  }, [controllerUrl, targetRpm])

  const sendTargetPosition = useCallback(async () => {
    try {
      const posValues: [number, number] = [
        typeof targetPosition[0] === 'string' ? (targetPosition[0] === '' ? 0 : Number(targetPosition[0])) : targetPosition[0],
        typeof targetPosition[1] === 'string' ? (targetPosition[1] === '' ? 0 : Number(targetPosition[1])) : targetPosition[1],
      ]
      const response = await axios.post(`${controllerUrl}/command/position`, posValues)
      console.log('Target position sent:', response.data)
    } catch (error) {
      console.error('Failed to send target position:', error)
    }
  }, [controllerUrl, targetPosition])

  const sendTargetAngle = useCallback(async () => {
    try {
      const angleValue = typeof targetAngle === 'string' ? (targetAngle === '' ? 0 : Number(targetAngle)) : targetAngle
      const response = await axios.post(`${controllerUrl}/command/angle`, [angleValue])
      console.log('Target angle sent:', response.data)
    } catch (error) {
      console.error('Failed to send target angle:', error)
    }
  }, [controllerUrl, targetAngle])

  const resetMotorPower = () => {
    setMotorPower([0, 0])
  }

  const sendReset = useCallback(async () => {
    try {
      const response = await axios.post(`${controllerUrl}/command/reset`)
      console.log('Reset command sent:', response.data)
      onReset?.()
    } catch (error) {
      console.error('Failed to send reset command:', error)
    }
  }, [controllerUrl, onReset])

  const setMaxMotorPower = () => {
    setMotorPower([1, 1])
  }

  return (
    <div className="control-panel-simple">
      <div className="panel-header">
        <h2>Control Commands</h2>
      </div>

      <div className="endpoint-grid">
        <section className="endpoint-card">
          <h3>Motor Power</h3>
          <p className="endpoint-note">POST /command/power with [motorA, motorB] in range [-1.0, 1.0]</p>
          <div className="motors-grid">
            {[0, 1].map((index) => (
              <div key={index} className="motor-control">
                <h4>Motor {index + 1}</h4>
                <div className="power-display">
                  <span className={`power-value ${motorPower[index] > 0 ? 'forward' : motorPower[index] < 0 ? 'backward' : ''}`}>
                    {motorPower[index].toFixed(2)}
                  </span>
                </div>
            
                <input
                  type="range"
                  min="-1"
                  max="1"
                  step="0.01"
                  value={motorPower[index]}
                  onChange={(e) => handleMotorPowerChange(index as 0 | 1, Number(e.target.value))}
                  className="slider"
                />

                <div className="motor-buttons">
                  <button
                    onClick={() => handleMotorPowerChange(index as 0 | 1, 0)}
                    className="btn btn-small btn-neutral"
                  >
                    Stop
                  </button>
                  <button
                    onClick={() => handleMotorPowerChange(index as 0 | 1, 0.5)}
                    className="btn btn-small btn-primary"
                  >
                    Half
                  </button>
                  <button
                    onClick={() => handleMotorPowerChange(index as 0 | 1, 1)}
                    className="btn btn-small btn-success"
                  >
                    Max
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div className="control-actions">
            <button onClick={resetMotorPower} className="btn btn-danger">
              Reset All
            </button>
            <button onClick={setMaxMotorPower} className="btn btn-success">
              Max All
            </button>
            <button onClick={sendMotorPower} className="btn btn-primary btn-send">
              Send /command/power
            </button>
          </div>
        </section>

        <section className="endpoint-card compact">
          <h3>Target RPM</h3>
          <p className="endpoint-note">POST /command/rpm with [rpm1, rpm2]</p>
          <div className="inline-inputs two-cols">
            <label>
              RPM 1
              <input
                type="number"
                value={targetRpm[0]}
                onChange={(e) => setTargetRpm([e.target.value, targetRpm[1]])}
                className="number-input"
              />
            </label>
            <label>
              RPM 2
              <input
                type="number"
                value={targetRpm[1]}
                onChange={(e) => setTargetRpm([targetRpm[0], e.target.value])}
                className="number-input"
              />
            </label>
          </div>
          <button onClick={sendTargetRpm} className="btn btn-primary">
            Send /command/rpm
          </button>
        </section>

        <section className="endpoint-card compact">
          <h3>Target Position</h3>
          <p className="endpoint-note">POST /command/position with [x, y] in mm</p>
          <div className="inline-inputs two-cols">
            <label>
              X (mm)
              <input
                type="number"
                value={targetPosition[0]}
                onChange={(e) => setTargetPosition([e.target.value, targetPosition[1]])}
                className="number-input"
              />
            </label>
            <label>
              Y (mm)
              <input
                type="number"
                value={targetPosition[1]}
                onChange={(e) => setTargetPosition([targetPosition[0], e.target.value])}
                className="number-input"
              />
            </label>
          </div>
          <button onClick={sendTargetPosition} className="btn btn-primary">
            Send /command/position
          </button>
        </section>

        <section className="endpoint-card compact">
          <h3>Target Angle</h3>
          <p className="endpoint-note">POST /command/angle with [theta] in degrees</p>
          <div className="inline-inputs">
            <label>
              Theta (deg)
              <input
                type="number"
                value={targetAngle}
                onChange={(e) => setTargetAngle(e.target.value)}
                className="number-input"
              />
            </label>
          </div>
          <button onClick={sendTargetAngle} className="btn btn-primary">
            Send /command/angle
          </button>
        </section>

        <section className="endpoint-card compact">
          <h3>Reset</h3>
          <p className="endpoint-note">POST /command/reset</p>
          <button onClick={sendReset} className="btn btn-danger">
            Send /command/reset
          </button>
        </section>
      </div>

      <VideoFeed controllerUrl={controllerUrl} />
    </div>
  )
}
