# Motor Control Server Documentation

## Overview
The `motor_control_server` is a Flask-based HTTP server that provides REST endpoints for controlling robot motors. It integrates with ROS2 to publish motor speed commands to the `/motor_speeds` topic.

## Installation

1. Install dependencies:
```bash
pip install flask flask-cors pygame
```

Or, in a ROS2 environment:
```bash
sudo apt-get install python3-flask python3-flask-cors
```

2. Build the ROS2 package:
```bash
cd /path/to/remote
colcon build
```

3. Source the setup files:
```bash
source install/setup.bash
```

## Running the Server

### Option 1: Using the entry point
```bash
ros2 run remote_control motor_control_server
```

Or directly:
```bash
motor_control_server
```

### Option 2: Running as a Python module
```bash
python3 -m remote_control.motor_control_server
```

The server will start on `http://0.0.0.0:5000` by default.

## API Endpoints

### 1. Health Check
**Endpoint:** `GET /health`

**Response:**
```json
{
  "status": "healthy",
  "service": "motor_control_server"
}
```

### 2. Send Motor Commands
**Endpoint:** `POST /motor/command`

**Request Body:**
```json
{
  "motors": [
    {"motor_id": 1, "power": 50},
    {"motor_id": 2, "power": -30}
  ]
}
```

**Parameters:**
- `motor_id` (integer): Motor identifier (1 = left motor, 2 = right motor)
- `power` (integer): Motor power/speed (-100 to 100)
  - Positive values: Forward
  - Negative values: Backward
  - 0: Stop

**Response (Success):**
```json
{
  "status": "success",
  "message": "Motor command received and published",
  "motors_received": [
    {"motor_id": 1, "power": 50},
    {"motor_id": 2, "power": -30}
  ]
}
```

**Response (Error):**
```json
{
  "error": "Missing motors field"
}
```

**Status Codes:**
- `200 OK`: Command successfully published
- `400 Bad Request`: Invalid request format
- `500 Internal Server Error`: Server error

## Frontend Usage Example

```typescript
// Send motor command from frontend
const response = await axios.post('http://localhost:5000/motor/command', {
  motors: [
    { motor_id: 1, power: 50 },
    { motor_id: 2, power: -30 }
  ]
});

// Check server health
const health = await axios.get('http://localhost:5000/health');
console.log(health.data); // { status: 'healthy', service: 'motor_control_server' }
```

## Motor Mapping

The motor control server expects the following motor ID mapping:
- **Motor 1**: Left motor (array index 0)
- **Motor 2**: Right motor (array index 1)

This mapping can be customized in the `publish_motor_command()` method of the `MotorPublisher` class.

## ROS2 Integration

The server publishes motor commands to the ROS2 topic `/motor_speeds` as `Int16MultiArray` messages with the format `[left_speed, right_speed]`.

To monitor motor commands in ROS2:
```bash
ros2 topic echo /motor_speeds
```

## Configuration

### Custom Port
To run on a custom port, modify the `run_flask_server()` call in the `main()` function:
```python
run_flask_server(motor_publisher, host='0.0.0.0', port=8080)
```

### Motor Mapping
Edit the `publish_motor_command()` method in the `MotorPublisher` class to customize motor ID mapping.

## Troubleshooting

### Port Already in Use
If port 5000 is already in use, change the port in the server configuration or kill the existing process:
```bash
lsof -i :5000
kill -9 <PID>
```

### CORS Issues
If you encounter CORS errors from the frontend, ensure `flask-cors` is installed. The server has CORS enabled by default for all endpoints.

### Connection Issues
- Verify the server is running: `curl http://localhost:5000/health`
- Check firewall settings if accessing from a remote machine
- Verify the frontend is using the correct server URL

## Development Notes

- The server runs Flask in a separate thread while ROS2 spins in the main thread
- Motor commands are clipped to [-100, 100] range
- All motor commands are logged to the ROS2 logger
