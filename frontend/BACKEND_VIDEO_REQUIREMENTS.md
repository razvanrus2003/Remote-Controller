# Video Feed Backend Requirements

## Overview
The frontend video feed component expects a **MJPEG (Motion JPEG)** stream from the backend at **1280×720 resolution** with **30 FPS**. This is a simple, browser-native format that doesn't require complex decoders.

### Required Video Specifications
- **Resolution**: 1280 × 720 pixels (16:9 aspect ratio)
- **Frame Rate**: 30 FPS (frames per second)
- **Format**: MJPEG (Motion JPEG)
- **Content-Type**: multipart/x-mixed-replace; boundary=frame
- **JPEG Quality**: 75-85 (for optimal balance of quality and bandwidth)

---

## Endpoint Specification

### URL
```
GET http://{backend-host}:{port}/video
```

### Example
```
GET http://192.168.1.132:5000/video
```

### Response Headers
```
Content-Type: multipart/x-mixed-replace; boundary=frame
Connection: keep-alive
Cache-Control: no-cache
Pragma: no-cache
Transfer-Encoding: chunked
```

### Response Body Format (MJPEG Stream)
The response should stream continuous JPEG frames separated by boundaries:

```
--frame
Content-Type: image/jpeg
Content-Length: {size_in_bytes}

{raw_jpeg_bytes}
--frame
Content-Type: image/jpeg
Content-Length: {size_in_bytes}

{raw_jpeg_bytes}
--frame
...
```

---

## Implementation Examples

### Python + Flask (Recommended)

```python
import cv2
from flask import Flask, Response
from threading import Thread

app = Flask(__name__)

class CameraStream:
    def __init__(self):
        self.frame = None
        self.lock = threading.Lock()
        self.capture_thread = Thread(target=self._capture_frames, daemon=True)
        self.capture_thread.start()
    
    def _capture_frames(self):
        """Continuously capture frames from camera"""
        cap = cv2.VideoCapture(0)  # 0 for default camera, or path to camera
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)  # REQUIRED: 1280x720
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)  # REQUIRED: 1280x720
        cap.set(cv2.CAP_PROP_FPS, 30)
        
        while True:
            ret, frame = cap.read()
            if ret:
                with self.lock:
                    self.frame = frame
            else:
                print("Failed to read from camera")
                break
        
        cap.release()
    
    def get_frame(self):
        """Get the latest frame"""
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

# Global camera instance
camera_stream = CameraStream()

@app.route('/video')
def video_feed():
    """MJPEG video stream endpoint"""
    def generate():
        while True:
            frame = camera_stream.get_frame()
            
            if frame is None:
                continue
            
            # Encode frame to JPEG
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            
            if not ret:
                continue
            
            frame_bytes = buffer.tobytes()
            
            # Yield frame in MJPEG format
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n'
                   b'X-Timestamp: ' + str(int(time.time() * 1000)).encode() + b'\r\n\r\n'
                   + frame_bytes + b'\r\n')
    
    return Response(
        generate(),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        }
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
```

### Python + FastAPI

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import cv2
import threading
import time

app = FastAPI()

class VideoCamera:
    def __init__(self):
        self.frame = None
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._read_frames, daemon=True)
        self.thread.start()
    
    def _read_frames(self):
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)  # REQUIRED: 1280x720
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)  # REQUIRED: 1280x720
        cap.set(cv2.CAP_PROP_FPS, 30)
        
        while True:
            ret, frame = cap.read()
            if ret:
                with self.lock:
                    self.frame = frame
            time.sleep(0.02)
    
    def get_frame(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

camera = VideoCamera()

@app.get("/video")
async def video_feed():
    def generate():
        while True:
            frame = camera.get_frame()
            if frame is None:
                continue
            
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ret:
                continue
            
            frame_bytes = buffer.tobytes()
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n\r\n'
                   + frame_bytes + b'\r\n')
    
    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
```

### Node.js + Express

```javascript
const express = require('express');
const cv = require('opencv4nodejs');
const app = express();

let camera = null;

function initCamera() {
  camera = new cv.VideoCapture(0);
  camera.set(cv.CAP_PROP_FRAME_WIDTH, 1280);  // REQUIRED: 1280x720
  camera.set(cv.CAP_PROP_FRAME_HEIGHT, 720);  // REQUIRED: 1280x720
  camera.set(cv.CAP_PROP_FPS, 30);
}

app.get('/video', (req, res) => {
  res.setHeader('Content-Type', 'multipart/x-mixed-replace; boundary=frame');
  res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
  res.setHeader('Pragma', 'no-cache');
  res.setHeader('Connection', 'keep-alive');

  const streamVideo = () => {
    if (!camera) initCamera();

    try {
      const frame = camera.read();
      const jpegData = cv.imwrite('.jpg', frame);
      const size = jpegData.length;

      const chunk = Buffer.concat([
        Buffer.from('--frame\r\n'),
        Buffer.from('Content-Type: image/jpeg\r\n'),
        Buffer.from(`Content-Length: ${size}\r\n\r\n`),
        jpegData,
        Buffer.from('\r\n')
      ]);

      res.write(chunk);
      setTimeout(streamVideo, 33); // ~30 FPS
    } catch (error) {
      console.error('Error streaming video:', error);
      res.end();
    }
  };

  streamVideo();
});

app.listen(5000, () => console.log('Video stream running on port 5000'));
```

---

## Key Requirements Checklist

- ✅ Endpoint at `/video`
- ✅ Content-Type: `multipart/x-mixed-replace; boundary=frame`
- ✅ Each frame separated by `--frame\r\n`
- ✅ Each frame has headers:
  - `Content-Type: image/jpeg`
  - `Content-Length: {bytes}`
- ✅ Valid JPEG binary data for each frame
- ✅ Continuous stream (don't close connection)
- ✅ No buffering (use streaming/chunked encoding)
- ✅ CORS headers if frontend is on different domain

---

## Performance Optimization Tips

### 1. Frame Rate
```python
# Adjust based on robot's capabilities and network bandwidth
# For 1280x720 resolution (recommended):
# 15 FPS for low bandwidth / mobile
# 20-25 FPS for balanced performance
# 30 FPS for good quality (optimal)
cap.set(cv2.CAP_PROP_FPS, 30)
```

### 2. JPEG Quality
```python
# Lower quality = smaller file size, faster streaming
# Recommended: 75-85 for 1280x720
cv2.IMWRITE_JPEG_QUALITY = 80  # 0-100, default 95
```

### 3. Resolution
```python
# **REQUIRED: 1280x720 (16:9)**
# Do not change - frontend expects this resolution
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
```

### 4. Threading
Always capture frames in a separate thread to avoid blocking the HTTP response.

---

## Testing the Endpoint

### Using curl
```bash
curl -N http://192.168.1.132:5000/video > video_stream.mjpeg
```

### Using Python
```python
import cv2

stream = cv2.VideoCapture('http://192.168.1.132:5000/video')

while True:
    ret, frame = stream.read()
    if not ret:
        break
    
    cv2.imshow('Stream', frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

stream.release()
cv2.destroyAllWindows()
```

### Using VLC
```
File → Open Network Stream → http://192.168.1.132:5000/video
```

---

## CORS Configuration

If the frontend is served from a different origin, add CORS headers:

```python
from flask_cors import CORS

CORS(app, resources={r"/video": {
    "origins": "*",
    "methods": ["GET", "OPTIONS"],
    "allow_headers": ["Content-Type"]
}})
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| 404 Not Found | Check endpoint URL matches `/video` |
| No video display | Verify Content-Type header is exactly `multipart/x-mixed-replace; boundary=frame` |
| Laggy/frozen video | Reduce frame rate, lower JPEG quality, or check network bandwidth |
| Connection timeout | Add keep-alive headers and ensure stream is continuous |
| CORS errors | Configure CORS headers on backend or use proxy |

---

## Security Considerations

- Add authentication to `/video` endpoint
- Validate camera source
- Rate limit if exposing publicly
- Use HTTPS in production
- Consider adding encryption for sensitive environments
