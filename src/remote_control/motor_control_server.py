import rclpy
from rclpy.node import Node
from std_msgs.msg import Int16MultiArray
from std_msgs.msg import String
from sensor_msgs.msg import CompressedImage
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import threading
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MotorPublisher(Node):
    """ROS2 node that publishes motor commands"""
    
    def __init__(self):
        super().__init__('motor_control_server')
        self.publisher = self.create_publisher(Int16MultiArray, '/motor_speeds', 10)
        self.health_subscription = self.create_subscription(String, '/health', self.handle_health_message, 10)
        # Frame buffer for MJPEG streaming (expects CompressedImage on /camera/image/compressed)
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.frame_event = threading.Event()
        self.image_subscription = self.create_subscription(CompressedImage, '/camera/image/compressed', self.handle_image, 10)
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

    def is_health_stale(self):
        if self.last_health_received_at is None:
            return True

        return (time.monotonic() - self.last_health_received_at) > self.health_timeout_sec
    
    def publish_motor_command(self, motors):
        """Publish motor speeds from frontend command
        
        Args:
            motors: List of motor commands, e.g., [{"motor_id": 1, "power": 50}, ...]
        """
        try:
            # Convert motor commands to speed array
            # Assuming motor_id maps to index: motor_id 1 -> left speed, motor_id 2 -> right speed
            speeds = [0, 0]
            
            for motor in motors:
                motor_id = motor.get('motor_id', 0)
                power = motor.get('power', 0)
                
                # Clamp power between -100 and 100
                power = max(min(power, self.max_speed), -self.max_speed)
                
                # Map motor_id to array index (1-based to 0-based)
                if 1 <= motor_id <= len(speeds):
                    speeds[motor_id - 1] = int(power)
            
            # Publish to ROS2
            msg = Int16MultiArray()
            msg.data = speeds
            self.publisher.publish(msg)
            self.last_motors = motors
            
            self.get_logger().info(f'Published motor speeds: {speeds}')
            return True
            
        except Exception as e:
            self.get_logger().error(f'Error publishing motor command: {e}')
            return False


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
    
    @app.route('/motor/command', methods=['POST'])
    def receive_motor_command():
        """Receive motor commands from frontend
        
        Expected payload:
        {
            "motors": [
                {"motor_id": 1, "power": 50},
                {"motor_id": 2, "power": -30}
            ]
        }
        """
        try:
            data = request.get_json()
            
            if not data or 'motors' not in data:
                return jsonify({'error': 'Missing motors field'}), 400
            
            motors = data['motors']
            
            # Validate motors data
            if not isinstance(motors, list) or len(motors) == 0:
                return jsonify({'error': 'motors must be a non-empty array'}), 400
            
            # Publish the motor command
            success = motor_publisher.publish_motor_command(motors)
            
            if success:
                return jsonify({
                    'status': 'success',
                    'message': 'Motor command received and published',
                    'motors_received': motors
                }), 200
            else:
                return jsonify({'error': 'Failed to publish motor command'}), 500
                
        except Exception as e:
            logger.error(f'Error processing motor command: {e}')
            return jsonify({'error': str(e)}), 500
    
    return app


def run_flask_server(motor_publisher, host='0.0.0.0', port=5000):
    """Run Flask server in a separate thread"""
    app = create_app(motor_publisher)
    logger.info(f'Starting Flask server on {host}:{port}')
    app.run(host=host, port=port, debug=False, use_reloader=False)


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
