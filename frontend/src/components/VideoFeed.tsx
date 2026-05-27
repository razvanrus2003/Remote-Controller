import { useState, useEffect } from 'react'
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

export default function VideoFeed({ controllerUrl }: VideoFeedProps) {
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isDepthMapConnected, setIsDepthMapConnected] = useState(false)
  const [depthMapError, setDepthMapError] = useState<string | null>(null)
  const [obstacleStatus, setObstacleStatus] = useState<ObstacleStatus | null>(null)
  const baseController = (controllerUrl && controllerUrl.replace(/\/$/, ''))
  const videoStreamUrl = 'http://localhost:8080'
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

  const obstacleBadgeClass = obstacleStatus?.blocked
    ? 'blocked'
    : obstacleStatus?.status === 'clear'
      ? 'clear'
      : 'unknown'

  return (
    <div className="video-feed-section">
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
