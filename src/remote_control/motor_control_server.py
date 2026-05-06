import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import CompressedImage
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import threading
import logging
import time
import subprocess
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MotorPublisher(Node):
    """ROS2 node that publishes motor commands"""
    
    def __init__(self):
        super().__init__('motor_control_server')
        self.command_topic_name = 'command'
        self.command_publisher = self.create_publisher(String, self.command_topic_name, 10)
        
        self.health_subscription = self.create_subscription(String, '/health', self.handle_health_message, 10)
        # Frame buffer for MJPEG streaming (expects CompressedImage on /camera/image/compressed)
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.frame_event = threading.Event()
        self.image_subscription = self.create_subscription(CompressedImage, '/camera/image/compressed', self.handle_image, 10)
        
        # Telemetry subscription for robot position and state
        self.latest_telemetry = None
        self.telemetry_lock = threading.Lock()
        self.telemetry_subscription = self.create_subscription(String, '/position', self.handle_telemetry, 10)
        
        self.max_speed = 100
        self.last_motors = None
        self.last_health = 'health topic not published yet'
        self.last_health_received_at = None
        self.health_timeout_sec = 3.0
        self.get_logger().info('Motor publisher initialized')

    def handle_health_message(self, msg):
        self.last_health = msg.data
        self.last_health_received_at = time.monotonic()

    def handle_image(self, msg: CompressedImage):
        """Handle incoming compressed image frames (JPEG bytes)"""
        try:
            # CompressedImage.data is a sequence of bytes representing JPEG
            frame_bytes = bytes(msg.data)
            with self.frame_lock:
                self.latest_frame = frame_bytes
                # notify any waiting HTTP generator
                self.frame_event.set()
        except Exception as e:
            self.get_logger().warning(f'Failed to handle incoming image: {e}')

    def handle_telemetry(self, msg: String):
        """Handle incoming robot telemetry data"""
        try:
            with self.telemetry_lock:
                self.latest_telemetry = msg.data
        except Exception as e:
            self.get_logger().warning(f'Failed to handle telemetry: {e}')

    def is_health_stale(self):
        if self.last_health_received_at is None:
            return True

        return (time.monotonic() - self.last_health_received_at) > self.health_timeout_sec

    def publish_power_command(self, motor_a, motor_b):
        """Publish direct power mode command (M command)
        
        Args:
            motor_a: Power for motor A (-1.0 to 1.0)
            motor_b: Power for motor B (-1.0 to 1.0)
        """
        try:
            motor_a = max(-1.0, min(1.0, float(motor_a)))
            motor_b = max(-1.0, min(1.0, float(motor_b)))

            return self.publish_command(f'M,{motor_a:g},{motor_b:g}')
        except Exception as e:
            self.get_logger().error(f'Error publishing power command: {e}')
            return False

    def publish_rpm_command(self, rpm1, rpm2):
        """Publish speed control command with RPM (R command)
        
        Args:
            rpm1: Target RPM for motor 1
            rpm2: Target RPM for motor 2
        """
        try:
            rpm1 = float(rpm1)
            rpm2 = float(rpm2)

            return self.publish_command(f'R,{rpm1:g},{rpm2:g}')
        except Exception as e:
            self.get_logger().error(f'Error publishing RPM command: {e}')
            return False

    def publish_position_command(self, x, y):
        """Publish position control command (P command)
        
        Args:
            x: Target X position in mm
            y: Target Y position in mm
        """
        try:
            x = float(x)
            y = float(y)

            return self.publish_command(f'P,{x:g},{y:g}')
        except Exception as e:
            self.get_logger().error(f'Error publishing position command: {e}')
            return False

    def publish_angle_command(self, theta):
        """Publish angle control command (A command)
        
        Args:
            theta: Target heading angle in degrees
        """
        try:
            theta = float(theta)

            return self.publish_command(f'A,{theta:g}')
        except Exception as e:
            self.get_logger().error(f'Error publishing angle command: {e}')
            return False

    def publish_reset_command(self):
        """Publish reset command"""
        try:
            return self.publish_command('RESET')
        except Exception as e:
            self.get_logger().error(f'Error publishing reset command: {e}')
            return False

    def publish_command(self, command_text):
        """Publish raw command string to unified command topic"""
        msg = String()
        msg.data = command_text
        self.command_publisher.publish(msg)

        self.get_logger().info(f'Published command to {self.command_topic_name}: {msg.data}')
        return True


def create_app(motor_publisher):
    """Create and configure Flask application"""
    
    app = Flask(__name__)
    CORS(app)  # Enable CORS for frontend requests
    
    @app.route('/health', methods=['GET'])
    def health_check():
        """Forward the latest /health topic payload from the robot."""
        if motor_publisher.is_health_stale():
            return jsonify({
                'error': 'health publisher disconnected or robot is off',
                'status': 'unhealthy',
            }), 503

        return jsonify({
            'status': 'healthy',
            'health': motor_publisher.last_health,
        }), 200

    @app.route('/position', methods=['GET'])
    def get_position():
        """Return the latest robot telemetry data"""
        with motor_publisher.telemetry_lock:
            telemetry = motor_publisher.latest_telemetry
        
        if not telemetry:
            return jsonify({
                'error': 'No telemetry data available',
                'status': 'no_data',
            }), 503
        
        return telemetry, 200, {'Content-Type': 'application/json'}

    @app.route('/video')
    def video_feed():
        """Return an MJPEG stream of the latest camera frames.

        Expects `motor_publisher` to subscribe to `sensor_msgs/CompressedImage`
        and keep the latest JPEG bytes in `latest_frame`.
        """
        def generate():
            boundary = b'frame'
            while True:
                # Wait for a frame to be available
                motor_publisher.frame_event.wait(timeout=5.0)
                with motor_publisher.frame_lock:
                    frame = motor_publisher.latest_frame
                    # clear event so we wait for next frame
                    motor_publisher.frame_event.clear()

                if not frame:
                    # no frame yet; yield a tiny sleep to avoid busy loop
                    time.sleep(0.1)
                    continue

                part = (b'--' + boundary + b'\r\n'
                        b'Content-Type: image/jpeg\r\n'
                        b'Content-Length: ' + str(len(frame)).encode() + b'\r\n\r\n' + frame + b'\r\n')
                yield part

        return Response(stream_with_context(generate()),
                        mimetype='multipart/x-mixed-replace; boundary=frame')
    
    @app.route('/command/power', methods=['POST'])
    def receive_power_command():
        """Receive direct power mode command
        
        Expected payload:
        [motorA, motorB]  - Power values from -1.0 to 1.0
        """
        try:
            data = request.get_json()
            
            if not isinstance(data, list) or len(data) != 2:
                return jsonify({'error': 'Expected array of [motorA, motorB]'}), 400
            
            success = motor_publisher.publish_power_command(data[0], data[1])
            if success:
                return jsonify({
                    'status': 'success',
                    'values': data
                }), 200
            else:
                return jsonify({'error': 'Failed to publish power command'}), 500
                
        except Exception as e:
            logger.error(f'Error processing power command: {e}')
            return jsonify({'error': str(e)}), 500
    
    @app.route('/command/rpm', methods=['POST'])
    def receive_rpm_command():
        """Receive RPM speed control command
        
        Expected payload:
        [rpm1, rpm2]  - RPM values for motors
        """
        try:
            data = request.get_json()
            
            if not isinstance(data, list) or len(data) != 2:
                return jsonify({'error': 'Expected array of [rpm1, rpm2]'}), 400
            
            success = motor_publisher.publish_rpm_command(data[0], data[1])
            if success:
                return jsonify({
                    'status': 'success',
                    'values': data
                }), 200
            else:
                return jsonify({'error': 'Failed to publish RPM command'}), 500
                
        except Exception as e:
            logger.error(f'Error processing RPM command: {e}')
            return jsonify({'error': str(e)}), 500
    
    @app.route('/command/position', methods=['POST'])
    def receive_position_command():
        """Receive position control command
        
        Expected payload:
        [x, y]  - Target position in mm
        """
        try:
            data = request.get_json()
            
            if not isinstance(data, list) or len(data) != 2:
                return jsonify({'error': 'Expected array of [x, y]'}), 400
            
            success = motor_publisher.publish_position_command(data[0], data[1])
            if success:
                return jsonify({
                    'status': 'success',
                    'values': data
                }), 200
            else:
                return jsonify({'error': 'Failed to publish position command'}), 500
                
        except Exception as e:
            logger.error(f'Error processing position command: {e}')
            return jsonify({'error': str(e)}), 500
    
    @app.route('/command/angle', methods=['POST'])
    def receive_angle_command():
        """Receive angle control command
        
        Expected payload:
        [theta]  - Target heading angle in degrees
        """
        try:
            data = request.get_json()
            
            if not isinstance(data, list) or len(data) != 1:
                return jsonify({'error': 'Expected array of [theta]'}), 400
            
            success = motor_publisher.publish_angle_command(data[0])
            if success:
                return jsonify({
                    'status': 'success',
                    'values': data
                }), 200
            else:
                return jsonify({'error': 'Failed to publish angle command'}), 500
                
        except Exception as e:
            logger.error(f'Error processing angle command: {e}')
            return jsonify({'error': str(e)}), 500

    @app.route('/command/reset', methods=['POST'])
    def receive_reset_command():
        """Receive reset command"""
        try:
            success = motor_publisher.publish_reset_command()
            if success:
                return jsonify({'status': 'success', 'command': 'reset'}), 200
            return jsonify({'error': 'Failed to publish reset command'}), 500
        except Exception as e:
            logger.error(f'Error processing reset command: {e}')
            return jsonify({'error': str(e)}), 500
    
    return app


def run_flask_server(motor_publisher, host='0.0.0.0', port=5000):
    """Run Flask server in a separate thread"""
    app = create_app(motor_publisher)
    logger.info(f'Starting Flask server on {host}:{port}')
    app.run(host=host, port=port, debug=False, use_reloader=False)


def run_frontend_dev_server():
    """Run frontend Vite dev server in a separate thread"""
    try:
        frontend_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'frontend')
        frontend_dir = os.path.abspath(frontend_dir)
        
        logger.info(f'Starting frontend from: {frontend_dir}')
        
        # Install dependencies if needed
        logger.info('Installing frontend dependencies...')
        subprocess.run(
            ['npm', 'install'],
            cwd=frontend_dir,
            check=False
        )
        
        # Build frontend if needed
        logger.info('Building frontend...')
        subprocess.run(
            ['npm', 'run', 'build'],
            cwd=frontend_dir,
            check=False
        )
        
        # Run dev server
        logger.info('Starting frontend dev server...')
        subprocess.run(
            ['npm', 'run', 'dev'],
            cwd=frontend_dir,
            check=False
        )
    except Exception as e:
        logger.error(f'Error running frontend: {e}')


def spin_ros2(motor_publisher):
    """Spin ROS2 node"""
    rclpy.spin(motor_publisher)


def main(args=None):
    """Main entry point for motor control server"""
    
    # Initialize ROS2
    rclpy.init(args=args)
    motor_publisher = MotorPublisher()
    
    try:
        # Start Flask server in a separate thread
        flask_thread = threading.Thread(
            target=run_flask_server,
            args=(motor_publisher,),
            daemon=False
        )
        flask_thread.start()
        
        # Start frontend dev server in a separate thread
        frontend_thread = threading.Thread(
            target=run_frontend_dev_server,
            daemon=False
        )
        frontend_thread.start()
        
        # Run ROS2 spin in main thread
        spin_ros2(motor_publisher)
        
    except KeyboardInterrupt:
        motor_publisher.get_logger().info('Server interrupted by user')
    except rclpy.executors.ExternalShutdownException:
        motor_publisher.get_logger().info('ROS2 shutdown externally')
    finally:
        try:
            motor_publisher.destroy_node()
        except Exception as e:
            motor_publisher.get_logger().warning(f'Error destroying node: {e}')
        
        try:
            rclpy.shutdown()
        except Exception as e:
            motor_publisher.get_logger().warning(f'Error during ROS2 shutdown: {e}')


if __name__ == '__main__':
    main()
