import { useState, useCallback } from 'react'
import axios from 'axios'
import VideoFeed from './VideoFeed'
import '../styles/RobotControlPanel.css'

interface MotorCommand {
  motor_id: number
  power: number
}

export default function RobotControlPanel() {
  const [motors, setMotors] = useState<MotorCommand[]>([
    { motor_id: 1, power: 0 },
    { motor_id: 2, power: 0 },
  ])

  const controllerUrl = 'http://192.168.1.132:5000'

  const handleMotorChange = (motorId: number, newPower: number) => {
    setMotors(motors.map(m => 
      m.motor_id === motorId ? { ...m, power: Math.max(-100, Math.min(100, newPower)) } : m
    ))
  }

  const sendMotorCommand = useCallback(async () => {
    try {
      const response = await axios.post(`${controllerUrl}/motor/command`, { motors })
      console.log('Command sent:', response.data)
    } catch (error) {
      console.error('Failed to send command:', error)
    }
  }, [motors])

  const resetAllMotors = () => {
    setMotors(motors.map(m => ({ ...m, power: 0 })))
  }

  const setMaxPower = () => {
    setMotors(motors.map(m => ({ ...m, power: 100 })))
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

      <VideoFeed controllerUrl={controllerUrl} />
    </div>
  )
}
