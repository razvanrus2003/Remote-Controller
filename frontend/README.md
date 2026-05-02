# Robot Control Interface

A modern TypeScript + React web interface for controlling a robot via a remote controller. This UI communicates with a remote controller backend to forward commands to a Raspberry Pi or other robot hardware.

## Features

- **Motor Control Panel**: Real-time control of up to 2 motors with power sliders (-100% to +100%)
- **Sensor Visualization**: Display sensor data including temperature, humidity, distance, and battery level
- **Robot Position Tracking**: Visual representation of robot position on a map with trail history
- **Telemetry Graphs**: Speed history and other performance metrics
- **Modern UI**: Clean, responsive design with Material Design principles
- **Connection Status**: Real-time connection status indicator

## Architecture

```
Frontend (React/TypeScript) 
    ↓
Remote Controller API
    ↓
Robot (RPi/Hardware)
```

The UI sends motor commands to the remote controller, which forwards them to the robot hardware.

## Tech Stack

- **React 18** - UI framework
- **TypeScript** - Type-safe development
- **Vite** - Fast build tool and dev server
- **Axios** - HTTP client for API communication
- **CSS3** - Modern styling with CSS Grid and Flexbox

## Installation

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## Configuration

The default controller URL is `http://localhost:5000`. You can change this in the UI by:

1. Entering a new URL in the "Controller URL" field
2. Clicking "Test Connection" to verify connectivity

## Motor Control

### Motor IDs
- Motor 1-2: Individual motor control

### Power Range
- **-100%**: Full reverse
- **0%**: Stopped
- **+100%**: Full forward

### Quick Controls
- **Stop**: Set motor to 0%
- **Half**: Set motor to 50%
- **Max**: Set motor to 100%
- **Reset All**: Stop all motors
- **Max All**: Set all motors to 100%

## API Integration

### Required Endpoints

The remote controller should expose the following endpoints:

#### Health Check
```
GET /health
Response: { status: "ok" }
```

#### Motor Control
```json
POST /motor/command
Body: {
  motors: [
    { motor_id: 1, power: 0 },
    { motor_id: 2, power: 50 }
  ]
}
```

## Extensibility

### Adding Sensor Data Integration

To connect real sensor data, modify `src/components/SensorVisualization.tsx`:

```typescript
// Replace the simulated data fetch with real API calls
const fetchSensorData = async () => {
  const response = await axios.get(`${controllerUrl}/sensors`);
  setSensorData(response.data);
};
```

### Adding Position Tracking

Update `src/components/RobotPosition.tsx` to fetch real position data:

```typescript
const fetchPosition = async () => {
  const response = await axios.get(`${controllerUrl}/position`);
  setPosition(response.data);
};
```

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+

## Responsive Design

The interface is fully responsive and works on:
- Desktop (1920px+)
- Tablet (768px - 1024px)
- Mobile (320px - 767px)

## Development Notes

- The sensor data and position data currently use simulated/placeholder values
- The UI is ready to connect to real APIs by updating the API endpoints
- All components are modular and can be easily extended

## Future Enhancements

- [ ] Real-time sensor data streaming (WebSocket)
- [ ] Camera feed display
- [ ] Autonomous mode control
- [ ] Path planning visualization
- [ ] Emergency stop button
- [ ] Command history and logging
- [ ] Mobile app version

## License

Proprietary - Robot Control Project

## Support

For issues or questions, please refer to the main project documentation.
