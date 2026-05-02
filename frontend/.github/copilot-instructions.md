# Robot Control Interface - Development Guide

A modern React + TypeScript web interface for robot control. Communicates with a remote controller API to forward commands to RPi/hardware.

## Project Structure

```
src/
├── main.tsx                 # React entry point
├── App.tsx                  # Main app component
├── index.css               # Global styles
├── components/
│   ├── RobotControlPanel.tsx    # Motor control component
│   ├── SensorVisualization.tsx  # Sensor data display
│   └── RobotPosition.tsx        # Robot positioning & telemetry
└── styles/
    ├── RobotControlPanel.css
    ├── SensorVisualization.css
    └── RobotPosition.css
```

## Getting Started

```bash
npm install        # Install dependencies
npm run dev        # Start dev server (http://localhost:5173)
npm run build      # Build for production
npm run preview    # Preview production build
```

## Key Features

- **Motor Control**: 2 independent motor controls with -100% to +100% power range
- **Sensor Dashboard**: Temperature, humidity, distance, battery display
- **Position Tracking**: Robot position map with trail history
- **Telemetry**: Speed history graph
- **API-Ready**: Connects to remote controller backend

## Configuration

Default controller URL: `http://localhost:5000`

Change in the UI or create a `.env.local` file:
```
VITE_CONTROLLER_URL=http://your-controller:5000
```

## API Endpoints Expected

```
GET  /health              # Connection test
POST /motor/command       # Send motor commands
GET  /sensors            # Get sensor data (for integration)
GET  /position           # Get robot position (for integration)
```

## Customization

1. **Add Real Sensor Data**: Update `src/components/SensorVisualization.tsx`
2. **Add Real Position Tracking**: Update `src/components/RobotPosition.tsx`
3. **Modify UI Theme**: Edit color variables in `src/index.css`
4. **Add New Motors**: Extend the motors array in `RobotControlPanel.tsx`

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+

## Development Notes

- Sensor data currently uses simulated values
- Position data uses placeholder animations
- Replace with real API calls when backend is ready
- All components are modular and independently testable

## Troubleshooting

**Build fails with "Could not resolve"**: Run `npm install` again

**Connection refused**: Ensure remote controller is running and accessible at the configured URL

**Port already in use**: Vite will automatically use the next available port
