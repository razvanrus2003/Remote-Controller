import logging
import os
import threading
import time
import json

# try:
#     from .runtime_bootstrap import ensure_venv_python_has_onnxruntime
# except Exception:
#     try:
#         from remote_control.runtime_bootstrap import ensure_venv_python_has_onnxruntime
#     except Exception:
#         def ensure_venv_python_has_onnxruntime():
#             return

# ensure_venv_python_has_onnxruntime()

import rclpy
from rclpy.executors import MultiThreadedExecutor
from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import CompressedImage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CommandApiNode(Node):
    def __init__(self):
        super().__init__('remote_command_api')
        self.command_topic_name = 'command'
        self.command_publisher = self.create_publisher(String, self.command_topic_name, 10)
        self.health_timeout_sec = 3.0

        self.health_subscription = self.create_subscription(String, '/health', self.handle_health_message, 1)
        self.telemetry_subscription = self.create_subscription(String, '/position', self.handle_telemetry, 1)
        # Subscribe to obstacle analysis topic published by VideoMlNode
        self.latest_obstacle = None
        self.latest_obstacle_received_at = None
        self.obstacle_subscription = self.create_subscription(String, '/obstacle', self.handle_obstacle_message, 1)
        
        # Local runtime state and synchronization (replaces shared_state module)
        self.health_lock = threading.Lock()
        self.last_health = None
        self.last_health_received_at = None

        self.telemetry_lock = threading.Lock()
        self.latest_telemetry = None

        self.obstacle_lock = threading.Lock()
        self.latest_obstacle_state = None

        self.endpoint_frame_lock = threading.Lock()
        self.latest_frame_endpoint_received_at = None
        

    def handle_health_message(self, msg: String):
        with self.health_lock:
            self.last_health = msg.data
            self.last_health_received_at = time.monotonic()

    def handle_telemetry(self, msg: String):
        with self.telemetry_lock:
            self.latest_telemetry = msg.data

    def handle_obstacle_message(self, msg: String):
        try:
            obj = json.loads(msg.data)
        except Exception:
            obj = {'status': 'unknown', 'reason': 'invalid_obstacle_message', 'raw': msg.data}
        # keep a local copy for the API to serve; still update shared_state for compatibility
        try:
            with self.obstacle_lock:
                self.latest_obstacle_state = obj
        except Exception:
            pass
        self.latest_obstacle = obj
        self.latest_obstacle_received_at = time.monotonic()

    def is_health_stale(self):
        with self.health_lock:
            last_health_received_at = self.last_health_received_at

        if last_health_received_at is None:
            return True

        return (time.monotonic() - last_health_received_at) > self.health_timeout_sec

    def publish_command(self, command_text):
        msg = String()
        msg.data = command_text
        self.command_publisher.publish(msg)
        self.get_logger().info(f'Published command to {self.command_topic_name}: {msg.data}')
        return True

    def publish_power_command(self, motor_a, motor_b):
        try:
            motor_a = max(-1.0, min(1.0, float(motor_a)))
            motor_b = max(-1.0, min(1.0, float(motor_b)))
            return self.publish_command(f'M,{motor_a:g},{motor_b:g}')
        except Exception as e:
            self.get_logger().error(f'Error publishing power command: {e}')
            return False

    def publish_rpm_command(self, rpm1, rpm2):
        try:
            rpm1 = float(rpm1)
            rpm2 = float(rpm2)
            return self.publish_command(f'R,{rpm1:g},{rpm2:g}')
        except Exception as e:
            self.get_logger().error(f'Error publishing RPM command: {e}')
            return False

    def publish_position_command(self, x, y):
        try:
            x = float(x)
            y = float(y)
            return self.publish_command(f'P,{x:g},{y:g}')
        except Exception as e:
            self.get_logger().error(f'Error publishing position command: {e}')
            return False

    def publish_angle_command(self, theta):
        try:
            theta = float(theta)
            return self.publish_command(f'A,{theta:g}')
        except Exception as e:
            self.get_logger().error(f'Error publishing angle command: {e}')
            return False

    def publish_reset_command(self):
        try:
            return self.publish_command('RESET')
        except Exception as e:
            self.get_logger().error(f'Error publishing reset command: {e}')
            return False


def create_app(command_node: CommandApiNode):
    app = Flask(__name__)
    CORS(app)

    # NOTE: Video streaming is handled by the ROS `web_video_server` node.
    # The Flask endpoints below will redirect clients to the web_video_server
    # stream URLs. Configure the camera/depth topics via environment vars:
    # `CAMERA_TOPIC`, `DEPTH_TOPIC`, and `WEB_VIDEO_PORT`.

    # depth streaming is also handled by `web_video_server`; see routes below.

    @app.route('/health', methods=['GET'])
    def health_check():
        if command_node.is_health_stale():
            return jsonify({
                'error': 'health publisher disconnected or robot is off',
                'status': 'unhealthy',
            }), 503

        with command_node.health_lock:
            last_health = command_node.last_health

        return jsonify({
            'status': 'healthy',
            'health': last_health,
        }), 200

    @app.route('/position', methods=['GET'])
    def get_position():
        with command_node.telemetry_lock:
            telemetry = command_node.latest_telemetry

        if not telemetry:
            return jsonify({
                'error': 'No telemetry data available',
                'status': 'no_data',
            }), 503

        return telemetry, 200, {'Content-Type': 'application/json'}

    @app.route('/obstacle', methods=['GET'])
    def get_obstacle_status():
        # Prefer the latest obstacle analysis published on /depth_map/obstacle
        if command_node.latest_obstacle is None:
            # no obstacle messages received yet
            state = {
                'status': 'unknown',
                'reason': 'waiting for obstacle topic',
                'stale': True,
                'frame_age_sec': None,
            }
            return jsonify(state), 200

        state = dict(command_node.latest_obstacle)

        with command_node.endpoint_frame_lock:
            last_frame_at = command_node.latest_frame_endpoint_received_at

        if last_frame_at is None:
            state['stale'] = True
            state['frame_age_sec'] = None
            if state.get('status') == 'unknown':
                state['reason'] = 'waiting for camera frames'
            return jsonify(state), 200

        frame_age_sec = time.monotonic() - last_frame_at
        state['frame_age_sec'] = round(frame_age_sec, 3)
        state['stale'] = frame_age_sec > 1.5
        if state['stale'] and state.get('status') == 'unknown':
            state['reason'] = 'camera feed is stale'

        return jsonify(state), 200

    @app.route('/video')
    def video_feed():
        # Redirect clients to the `web_video_server` stream for the configured camera topic.
        camera_topic = os.environ.get('CAMERA_TOPIC', '/camera/image/compressed')
        web_port = os.environ.get('WEB_VIDEO_PORT', '8080')
        # Use request.host to keep hostname, but replace port with web_video_server port.
        host = request.host.split(':')[0]
        stream_url = f'http://{host}:{web_port}/stream?topic={camera_topic}'
        return jsonify({'stream_url': stream_url}), 302

    @app.route('/depth-map', methods=['GET'])
    def get_depth_map():
        depth_topic = os.environ.get('DEPTH_TOPIC', '/depth_map/image/compressed')
        web_port = os.environ.get('WEB_VIDEO_PORT', '8080')
        host = request.host.split(':')[0]
        stream_url = f'http://{host}:{web_port}/stream?topic={depth_topic}'
        return jsonify({'stream_url': stream_url}), 302

    @app.route('/command/power', methods=['POST'])
    def receive_power_command():
        try:
            data = request.get_json()
            if not isinstance(data, list) or len(data) != 2:
                return jsonify({'error': 'Expected array of [motorA, motorB]'}), 400

            success = command_node.publish_power_command(data[0], data[1])
            if success:
                return jsonify({'status': 'success', 'values': data}), 200
            return jsonify({'error': 'Failed to publish power command'}), 500
        except Exception as e:
            logger.error(f'Error processing power command: {e}')
            return jsonify({'error': str(e)}), 500

    @app.route('/command/rpm', methods=['POST'])
    def receive_rpm_command():
        try:
            data = request.get_json()
            if not isinstance(data, list) or len(data) != 2:
                return jsonify({'error': 'Expected array of [rpm1, rpm2]'}), 400

            success = command_node.publish_rpm_command(data[0], data[1])
            if success:
                return jsonify({'status': 'success', 'values': data}), 200
            return jsonify({'error': 'Failed to publish RPM command'}), 500
        except Exception as e:
            logger.error(f'Error processing RPM command: {e}')
            return jsonify({'error': str(e)}), 500

    @app.route('/command/position', methods=['POST'])
    def receive_position_command():
        try:
            data = request.get_json()
            if not isinstance(data, list) or len(data) != 2:
                return jsonify({'error': 'Expected array of [x, y]'}), 400

            success = command_node.publish_position_command(data[0], data[1])
            if success:
                return jsonify({'status': 'success', 'values': data}), 200
            return jsonify({'error': 'Failed to publish position command'}), 500
        except Exception as e:
            logger.error(f'Error processing position command: {e}')
            return jsonify({'error': str(e)}), 500

    @app.route('/command/angle', methods=['POST'])
    def receive_angle_command():
        try:
            data = request.get_json()
            if not isinstance(data, list) or len(data) != 1:
                return jsonify({'error': 'Expected array of [theta]'}), 400

            success = command_node.publish_angle_command(data[0])
            if success:
                return jsonify({'status': 'success', 'values': data}), 200
            return jsonify({'error': 'Failed to publish angle command'}), 500
        except Exception as e:
            logger.error(f'Error processing angle command: {e}')
            return jsonify({'error': str(e)}), 500

    @app.route('/command/pid', methods=['POST'])
    def receive_pid_command():
        try:
            data = request.get_json()

            if isinstance(data, list):
                if len(data) != 4:
                    return jsonify({'error': 'Expected array of [ctrl, kp, ki, kd]'}), 400
                ctrl = str(data[0]).upper()
                kp, ki, kd = data[1], data[2], data[3]
            elif isinstance(data, dict):
                ctrl = str(data.get('ctrl', '')).upper()
                try:
                    kp = float(data.get('kp'))
                    ki = float(data.get('ki'))
                    kd = float(data.get('kd'))
                except Exception:
                    return jsonify({'error': 'kp/ki/kd must be numeric'}), 400
            else:
                return jsonify({'error': 'Expected JSON array or object'}), 400

            if ctrl not in ['S', 'P', 'H', 'A']:
                return jsonify({'error': "ctrl must be one of 'S','P','H','A'"}), 400

            kp = float(kp)
            ki = float(ki)
            kd = float(kd)
            command_text = f'V,{ctrl},{kp:g},{ki:g},{kd:g}'
            success = command_node.publish_command(command_text)

            if success:
                return jsonify({'status': 'success', 'command': command_text}), 200
            return jsonify({'error': 'Failed to publish PID command'}), 500
        except Exception as e:
            logger.error(f'Error processing PID command: {e}')
            return jsonify({'error': str(e)}), 500

    @app.route('/command/pid/<ctrl>', methods=['POST'])
    def receive_pid_for_ctrl(ctrl):
        try:
            ctrl = str(ctrl).upper()
            if ctrl not in ['S', 'P', 'H', 'A']:
                return jsonify({'error': "ctrl must be one of 'S','P','H','A'"}), 400

            data = request.get_json()
            if isinstance(data, list):
                if len(data) != 3:
                    return jsonify({'error': 'Expected array of [kp, ki, kd]'}), 400
                kp, ki, kd = data[0], data[1], data[2]
            elif isinstance(data, dict):
                try:
                    kp = float(data.get('kp'))
                    ki = float(data.get('ki'))
                    kd = float(data.get('kd'))
                except Exception:
                    return jsonify({'error': 'kp/ki/kd must be numeric'}), 400
            else:
                return jsonify({'error': 'Expected JSON array or object'}), 400

            kp = float(kp)
            ki = float(ki)
            kd = float(kd)
            command_text = f'V,{ctrl},{kp:g},{ki:g},{kd:g}'
            success = command_node.publish_command(command_text)

            if success:
                return jsonify({'status': 'success', 'command': command_text}), 200
            return jsonify({'error': 'Failed to publish PID command'}), 500
        except Exception as e:
            logger.error(f'Error processing PID command for {ctrl}: {e}')
            return jsonify({'error': str(e)}), 500

    @app.route('/command/reset', methods=['POST'])
    def receive_reset_command():
        try:
            success = command_node.publish_reset_command()
            if success:
                return jsonify({'status': 'success', 'command': 'reset'}), 200
            return jsonify({'error': 'Failed to publish reset command'}), 500
        except Exception as e:
            logger.error(f'Error processing reset command: {e}')
            return jsonify({'error': str(e)}), 500

    return app


def run_flask_server(command_node: CommandApiNode, host='0.0.0.0', port=5000):
    app = create_app(command_node)
    logger.info(f'Starting Flask server on {host}:{port}')
    app.run(host=host, port=port, debug=False, use_reloader=False)


def main(args=None):
    rclpy.init(args=args)
    command_node = CommandApiNode()
    flask_thread = threading.Thread(target=run_flask_server, args=(command_node,), daemon=True)
    flask_thread.start()
    try:
        executor = MultiThreadedExecutor()
        executor.add_node(command_node)
        executor.spin()
    finally:
        command_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
