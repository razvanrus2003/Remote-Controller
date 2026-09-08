import { useState, useEffect, useRef } from 'react'
import '../styles/VideoFeed.css'

interface VideoFeedProps {
  controllerUrl?: string
}

interface ObstacleStatus {
  status: 'unknown' | 'clear' | 'blocked'
  blocked: boolean
  confidence: number
  reason: string
  updated_at: number | null
  frame_age_sec: number | null
  stale: boolean
}

interface MapInfo {
  width: number
  height: number
  resolution: number
  origin: {
    position: { x: number; y: number; z: number }
    orientation: { x: number; y: number; z: number; w: number }
  }
}

export default function VideoFeed({ controllerUrl }: VideoFeedProps) {
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isDepthMapConnected, setIsDepthMapConnected] = useState(false)
  const [depthMapError, setDepthMapError] = useState<string | null>(null)
  const [obstacleStatus, setObstacleStatus] = useState<ObstacleStatus | null>(null)
  const baseController = (controllerUrl && controllerUrl.replace(/\/$/, ''))
  const videoStreamUrl = 'http://localhost:8080'
  const [occupancyInfo, setOccupancyInfo] = useState<MapInfo | null>(null)
  const [occupancyData, setOccupancyData] = useState<number[] | null>(null)
  const occupancyCanvasRef = useRef<HTMLCanvasElement | null>(null)
  const [autoDriveEnabled, setAutoDriveEnabled] = useState(false)
  const [autoDriveLoading, setAutoDriveLoading] = useState(true)

  useEffect(() => {
    let mounted = true

    const fetchAutoDrive = async () => {
      try {
        const response = await fetch(`${baseController}/command/autodrive`)
        const data = await response.json()

        if (!mounted) return

        // Adjust this depending on your API response
        setAutoDriveEnabled(Boolean(data.enabled))
      } catch (err) {
        console.error('Failed to fetch autodrive status', err)
      } finally {
        if (mounted) {
          setAutoDriveLoading(false)
        }
      }
    }

    void fetchAutoDrive()

    return () => {
      mounted = false
    }
  }, [baseController])

const toggleAutoDrive = async () => {
  const newValue = !autoDriveEnabled

  setAutoDriveEnabled(newValue)

  try {
    await fetch(`${baseController}/command/autodrive`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        enabled: newValue,
      }),
    })
  } catch (err) {
    console.error('Failed to update autodrive', err)

    // revert on failure
    setAutoDriveEnabled(!newValue)
  }
}

  useEffect(() => {
    let isMounted = true

    const fetchObstacleStatus = async () => {
      try {
        const response = await fetch(`${baseController}/obstacle`)
        const data = (await response.json()) as ObstacleStatus

        if (!isMounted) {
          return
        }

        if (data && typeof data.status === 'string') {
          setObstacleStatus(data)
        }
      } catch (err) {
        console.error('Obstacle status error:', err)
        if (isMounted) {
          setObstacleStatus(null)
        }
      }
    }

    void fetchObstacleStatus()
    const interval = window.setInterval(() => {
      void fetchObstacleStatus()
    }, 1000)

    return () => {
      isMounted = false
      window.clearInterval(interval)
    }
  }, [baseController])

  useEffect(() => {
    let isMounted = true

    const fetchOccupancy = async () => {
      try {
        const resp = await fetch(`${baseController}/occupancy-grid`)
        const body = await resp.json()
        const info = body.info || (body.msg && body.msg.info) || null
        const data = body.data || (body.msg && body.msg.data) || null
        if (!isMounted) return
        if (info && data && Array.isArray(data)) {
          const parsed: MapInfo = {
            width: Number(info.width) || 0,
            height: Number(info.height) || 0,
            resolution: Number(info.resolution) || 0,
            origin: {
              position: { x: Number(info.origin?.position?.x) || 0, y: Number(info.origin?.position?.y) || 0, z: Number(info.origin?.position?.z) || 0 },
              orientation: {
                x: Number(info.origin?.orientation?.x) || 0,
                y: Number(info.origin?.orientation?.y) || 0,
                z: Number(info.origin?.orientation?.z) || 0,
                w: Number(info.origin?.orientation?.w) || 0,
              },
            },
          }
          setOccupancyInfo(parsed)
          setOccupancyData(Array.from(data).map((v: any) => Number(v)))
        }
      } catch (err) {
        // ignore
      }
    }

    void fetchOccupancy()
    const interval = window.setInterval(() => void fetchOccupancy(), 1000)
    return () => {
      isMounted = false
      window.clearInterval(interval)
    }
  }, [baseController])

  useEffect(() => {
    if (!occupancyInfo || !occupancyData || !occupancyCanvasRef.current) return
    const canvas = occupancyCanvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const w = occupancyInfo.width || 1
    const h = occupancyInfo.height || 1
    canvas.width = w
    canvas.height = h
    canvas.style.width = '200px'
    canvas.style.height = '200px'
    const img = ctx.createImageData(w, h)
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const idx = y * w + x
        const v = occupancyData[idx]
        let r: number, g: number, b: number

        if (v === -1) {
          // unexplored
          r = 0
          g = 0
          b = 0
        } else {
          // Clamp to [0,100]
          const t = Math.max(0, Math.min(100, v)) / 100

          // Green (0) -> Red (100)
          r = Math.round(255 * t)
          g = Math.round(255 * (1 - t))
          b = 0
        }

        const p = idx * 4
        img.data[p] = r
        img.data[p + 1] = g
        img.data[p + 2] = b
        img.data[p + 3] = 255
      }
    }
    ctx.putImageData(img, 0, 0)
  }, [occupancyInfo, occupancyData])

  const obstacleBadgeClass = obstacleStatus?.blocked
    ? 'blocked'
    : obstacleStatus?.status === 'clear'
      ? 'clear'
      : 'unknown'

  return (
    <div className="video-feed-section">
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>Auto Drive</span>
          <input
            type="checkbox"
            checked={autoDriveEnabled}
            disabled={autoDriveLoading}
            onChange={toggleAutoDrive}
          />
        </label>
      </div>
      <div className="occupancy-section">
          <div style={{ marginTop: 12 }}>
            <h4>Occupancy Map</h4>
            <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
              <canvas ref={occupancyCanvasRef} style={{ width: 200, height: 200, border: '1px solid #ccc' }} />
              <div style={{ fontSize: 12 }}>
                {occupancyInfo ? (
                  <pre style={{ margin: 0, maxWidth: 300, overflow: 'auto' }}>{JSON.stringify(occupancyInfo, null, 2)}</pre>
                ) : (
                  <div style={{ color: '#666' }}>No occupancy map available</div>
                )}
                <div style={{ marginTop: 6 }}><small>Data length: {occupancyData ? occupancyData.length : '—'}</small></div>
              </div>
            </div>
          </div>
        </div>
      <div className="streams-layout">
        <div className="video-column">
          <div className="video-header">
            <h3>Video Feed</h3>
            <div className="video-header-statuses">
              <div className={`video-status ${isConnected ? 'connected' : 'disconnected'}`}>
                {isConnected ? '🟢 Streaming' : '🔴 Offline'}
              </div>
              <div className={`obstacle-status ${obstacleBadgeClass}`}>
                {obstacleStatus?.blocked
                  ? `⚠️ Blocked (${Math.round(obstacleStatus.confidence * 100)}%)`
                  : obstacleStatus?.status === 'clear'
                    ? `✅ Clear (${Math.round(obstacleStatus.confidence * 100)}%)`
                    : '⏳ Obstacle check unavailable'}
              </div>
            </div>
          </div>

          <div className="video-container">
            <img
              src={`${videoStreamUrl}/stream?topic=/camera/image&type=ros_compressed`}
              alt="Robot Video Feed"
              className="video-stream"
              onError={() => {
                setIsConnected(false)
                setError('Failed to load video stream')
              }}
              onLoad={() => {
                setIsConnected(true)
                setError(null)
              }}
            />
            {!isConnected && (
              <div className="video-placeholder">
                <div className="placeholder-icon">📷</div>
                <div className="placeholder-text">
                  {error || 'Video stream connecting...'}
                </div>
                <small className="placeholder-hint">
                  Ensure the external camera publisher is running at <code>/stream?topic=/camera/image/compressed</code>
                </small>
              </div>
            )}
          </div>

          <div className="video-info">
            <small>MJPEG Stream • 1280×720 • Real-time video from robot camera</small>
          </div>

          <div className={`obstacle-banner ${obstacleStatus?.blocked ? 'blocked' : obstacleStatus?.status === 'clear' ? 'clear' : 'unknown'}`}>
            <strong>
              {obstacleStatus?.blocked ? 'Obstacle detected' : obstacleStatus?.status === 'clear' ? 'Path clear' : 'Obstacle status unavailable'}
            </strong>
            <span>
              {obstacleStatus
                ? `${obstacleStatus.reason} ${obstacleStatus.frame_age_sec !== null ? `• frame age ${obstacleStatus.frame_age_sec}s` : ''}`
                : 'Waiting for the backend obstacle detector to report a status.'}
            </span>
          </div>
        </div>

        <div className="depth-map-section">
          <div className="depth-map-header">
            <h4>Depth Video Feed</h4>
            <div className={`depth-map-status ${isDepthMapConnected ? 'connected' : 'disconnected'}`}>
              {isDepthMapConnected ? '🟢 Streaming' : '🔴 Connecting'}
            </div>
          </div>

          <div className="depth-map-container">
            <img
              src={`${videoStreamUrl}/stream?topic=/depth_map/image&type=ros_compressed`}
              alt="Robot Depth Video Feed"
              className="depth-map-stream"
              onError={() => {
                setIsDepthMapConnected(false)
                setDepthMapError('Failed to load depth stream')
              }}
              onLoad={() => {
                setIsDepthMapConnected(true)
                setDepthMapError(null)
              }}
            />
            {!isDepthMapConnected && (
              <div className="depth-map-placeholder">
                <div className="placeholder-icon">🗺️</div>
                <div className="placeholder-text">
                  {depthMapError || 'Depth video unavailable'}
                </div>
                <small className="placeholder-hint">
                  Ensure backend depth publisher is running at <code>/stream?topic=/depth_map/image/compressed</code>
                </small>
              </div>
            )}
          </div>

          <div className="depth-map-info">
            <small>Live depth stream • /stream?topic=/depth_map/image/compressed • Matching dimensions to the video feed</small>
          </div>
        </div>
      </div>
    </div>
  )
}
