import { useState, useEffect } from 'react'
import '../styles/SensorVisualization.css'

interface SensorData {
  temperature: number
  humidity: number
  distance: number
  battery: number
}

export default function SensorVisualization() {
  const [sensorData, _setSensorData] = useState<SensorData>({
    temperature: 0,
    humidity: 0,
    distance: 0,
    battery: 0,
  })

  useEffect(() => {
    // TODO: Integrate real sensor data from /sensors endpoint
    // Example:
    // const fetchSensorData = async () => {
    //   try {
    //     const response = await axios.get(`${controllerUrl}/sensors`)
    //     setSensorData(response.data)
    //   } catch (error) {
    //     console.error('Failed to fetch sensor data:', error)
    //   }
    // }
    // const interval = setInterval(fetchSensorData, 1000)
    // return () => clearInterval(interval)
  }, [])

  return (
    <div className="sensor-panel">
      <h2>Sensor Data</h2>
      
      <div className="sensors-grid">
        <div className="sensor-card">
          <div className="sensor-icon">🌡️</div>
          <h3>Temperature</h3>
          <div className="sensor-value">{sensorData.temperature.toFixed(1)}°C</div>
          <div className="sensor-bar">
            <div 
              className="sensor-bar-fill" 
              style={{ width: `${Math.max(0, Math.min(100, (sensorData.temperature + 20) / 60 * 100))}%` }}
            ></div>
          </div>
        </div>

        <div className="sensor-card">
          <div className="sensor-icon">💧</div>
          <h3>Humidity</h3>
          <div className="sensor-value">{sensorData.humidity.toFixed(1)}%</div>
          <div className="sensor-bar">
            <div 
              className="sensor-bar-fill" 
              style={{ width: `${sensorData.humidity}%` }}
            ></div>
          </div>
        </div>

        <div className="sensor-card">
          <div className="sensor-icon">📏</div>
          <h3>Distance</h3>
          <div className="sensor-value">{sensorData.distance.toFixed(1)}cm</div>
          <div className="sensor-bar">
            <div 
              className="sensor-bar-fill" 
              style={{ width: `${Math.max(0, Math.min(100, sensorData.distance))}%` }}
            ></div>
          </div>
        </div>

        <div className="sensor-card">
          <div className="sensor-icon">🔋</div>
          <h3>Battery</h3>
          <div className="sensor-value">{sensorData.battery.toFixed(0)}%</div>
          <div className="sensor-bar">
            <div 
              className="sensor-bar-fill" 
              style={{ width: `${sensorData.battery}%` }}
            ></div>
          </div>
        </div>
      </div>
    </div>
  )
}
