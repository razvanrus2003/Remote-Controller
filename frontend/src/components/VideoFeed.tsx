import { useState, useEffect } from 'react'
import '../styles/VideoFeed.css'

interface VideoFeedProps {
  controllerUrl: string
}

export default function VideoFeed({ controllerUrl }: VideoFeedProps) {
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const videoUrl = `${controllerUrl}/video`
    
    // Test connection to video endpoint
    const testConnection = async () => {
      try {
        const response = await fetch(videoUrl, { method: 'HEAD' })
        if (response.ok || response.status === 206) { // 206 is Partial Content (for streaming)
          setIsConnected(true)
          setError(null)
        } else {
          setIsConnected(false)
          setError('Video endpoint returned error')
        }
      } catch (err) {
        console.error('Video connection error:', err)
        setIsConnected(false)
        setError('Cannot connect to video stream')
      }
    }

    testConnection()
  }, [controllerUrl])

  return (
    <div className="video-feed-section">
      <div className="video-header">
        <h3>Video Feed</h3>
        <div className={`video-status ${isConnected ? 'connected' : 'disconnected'}`}>
          {isConnected ? '🟢 Streaming' : '🔴 Offline'}
        </div>
      </div>

      <div className="video-container">
        {isConnected ? (
          <>
            <img 
              src={`${controllerUrl}/video`}
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
            <div className="video-info">
              <small>MJPEG Stream • 1280×720 • Real-time video from robot camera</small>
            </div>
          </>
        ) : (
          <div className="video-placeholder">
            <div className="placeholder-icon">📷</div>
            <div className="placeholder-text">
              {error || 'Video stream unavailable'}
            </div>
            <small className="placeholder-hint">
              Ensure backend /video endpoint is running
            </small>
          </div>
        )}
      </div>

      <div className="video-requirements">
        <details>
          <summary>Backend Requirements</summary>
          <div className="requirements-content">
            <h4>Endpoint: GET /video</h4>
            <p><strong>Content-Type:</strong> multipart/x-mixed-replace; boundary=frame</p>
            <p><strong>Purpose:</strong> Stream MJPEG (Motion JPEG) video frames continuously</p>
            
            <h4>Response Format:</h4>
            <pre>{`--frame
Content-Type: image/jpeg
Content-Length: {size}

{jpeg_image_bytes}
--frame
Content-Type: image/jpeg
Content-Length: {size}

{jpeg_image_bytes}
...`}</pre>

            <h4>Implementation Example (Python/Flask):</h4>
            <pre>{`@app.route('/video')
def video_feed():
    def generate():
        camera = Camera()  # Your camera object
        while True:
            frame = camera.get_frame()
            ret, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\\r\\n'
                   b'Content-Type: image/jpeg\\r\\n'
                   b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\\r\\n\\r\\n'
                   + frame_bytes + b'\\r\\n')
    
    return Response(generate(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')`}</pre>

            <h4>Key Requirements:</h4>
            <ul>
              <li>Endpoint must be at <code>/video</code></li>
              <li>Return MJPEG stream (multipart/x-mixed-replace)</li>
              <li>Each frame must be a valid JPEG image</li>
              <li>Use boundary separator <code>--frame</code></li>
              <li>Include Content-Type and Content-Length headers for each frame</li>
              <li>Continuous streaming (connection stays open)</li>
              <li>Typical frame rate: 15-30 FPS (configurable)</li>
              <li>Image resolution: 640x480 or 1280x720 recommended</li>
            </ul>

            <h4>CORS Configuration (if needed):</h4>
            <p>Add CORS headers to allow cross-origin requests:</p>
            <pre>{`'Access-Control-Allow-Origin': '*'
'Access-Control-Allow-Methods': 'GET, OPTIONS'
'Access-Control-Allow-Headers': 'Content-Type'`}</pre>
          </div>
        </details>
      </div>
    </div>
  )
}
