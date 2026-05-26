import logging
import threading
import time

from .runtime_bootstrap import ensure_venv_python_has_onnxruntime

ensure_venv_python_has_onnxruntime()

import rclpy
from rclpy.executors import MultiThreadedExecutor
from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS
from rclpy.node import Node
from std_msgs.msg import String

from .video_ml import VideoMlNode
from .shared_state import SharedRuntimeState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CommandApiNode(Node):
    def __init__(self, shared_state: SharedRuntimeState):
        super().__init__('remote_command_api')
        self.shared_state = shared_state
        self.command_topic_name = 'command'
        self.command_publisher = self.create_publisher(String, self.command_topic_name, 10)
        self.health_timeout_sec = 3.0

        self.health_subscription = self.create_subscription(String, '/health', self.handle_health_message, 10)
        self.telemetry_subscription = self.create_subscription(String, '/position', self.handle_telemetry, 10)

    def handle_health_message(self, msg: String):
        with self.shared_state.health_lock:
            self.shared_state.last_health = msg.data
            self.shared_state.last_health_received_at = time.monotonic()

    def handle_telemetry(self, msg: String):
        with self.shared_state.telemetry_lock:
            self.shared_state.latest_telemetry = msg.data

    def is_health_stale(self):
        with self.shared_state.health_lock:
            last_health_received_at = self.shared_state.last_health_received_at

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

    def generate_video_mjpeg():
        boundary = b'frame'
        last_processed_seq = -1

        while True:
            with command_node.shared_state.frame_lock:
                frame_seq = command_node.shared_state.latest_frame_seq
                frame_bytes = command_node.shared_state.latest_frame

            if frame_bytes is None or frame_seq == last_processed_seq:
                command_node.shared_state.frame_event.wait(timeout=5.0)
                continue

            last_processed_seq = frame_seq
            part = (
                b'--' + boundary + b'\r\n'
                b'Content-Type: image/jpeg\r\n'
                b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n\r\n' + frame_bytes + b'\r\n'
            )
            yield part

    def generate_depth_mjpeg():
        boundary = b'frame'
        last_processed_seq = -1

        while True:
            with command_node.shared_state.depth_map_lock:
                depth_jpeg = command_node.shared_state.latest_depth_map_jpeg
                depth_seq = command_node.shared_state.latest_depth_map_seq

            if depth_jpeg is None or depth_seq == last_processed_seq:
                command_node.shared_state.depth_event.wait(timeout=5.0)
                continue

            last_processed_seq = depth_seq
            part = (
                b'--' + boundary + b'\r\n'
                b'Content-Type: image/jpeg\r\n'
                b'Content-Length: ' + str(len(depth_jpeg)).encode() + b'\r\n\r\n' + depth_jpeg + b'\r\n'
            )
            yield part

    @app.route('/health', methods=['GET'])
    def health_check():
        if command_node.is_health_stale():
            return jsonify({
                'error': 'health publisher disconnected or robot is off',
                'status': 'unhealthy',
            }), 503

        with command_node.shared_state.health_lock:
            last_health = command_node.shared_state.last_health

        return jsonify({
            'status': 'healthy',
            'health': last_health,
        }), 200

    @app.route('/position', methods=['GET'])
    def get_position():
        with command_node.shared_state.telemetry_lock:
            telemetry = command_node.shared_state.latest_telemetry

        if not telemetry:
            return jsonify({
                'error': 'No telemetry data available',
                'status': 'no_data',
            }), 503

        return telemetry, 200, {'Content-Type': 'application/json'}

    @app.route('/obstacle', methods=['GET'])
    def get_obstacle_status():
        with command_node.shared_state.obstacle_lock:
            state = dict(command_node.shared_state.latest_obstacle_state)

        with command_node.shared_state.frame_lock:
            last_frame_at = command_node.shared_state.latest_frame_received_at

        if last_frame_at is None:
            state['stale'] = True
            state['frame_age_sec'] = None
            if state['status'] == 'unknown':
                state['reason'] = 'waiting for camera frames'
            return jsonify(state), 200

        frame_age_sec = time.monotonic() - last_frame_at
        state['frame_age_sec'] = round(frame_age_sec, 3)
        state['stale'] = frame_age_sec > 1.5
        if state['stale'] and state['status'] == 'unknown':
            state['reason'] = 'camera feed is stale'

        return jsonify(state), 200

    @app.route('/video')
    def video_feed():
        return Response(
            stream_with_context(generate_video_mjpeg()),
            mimetype='multipart/x-mixed-replace; boundary=frame',
            headers={'Cache-Control': 'no-store'},
        )

    @app.route('/depth-map', methods=['GET'])
    def get_depth_map():
        return Response(
            stream_with_context(generate_depth_mjpeg()),
            mimetype='multipart/x-mixed-replace; boundary=frame',
            headers={'Cache-Control': 'no-store'},
        )

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
    shared_state = SharedRuntimeState()
    command_node = CommandApiNode(shared_state)
    video_node = VideoMlNode(shared_state)
    flask_thread = threading.Thread(target=run_flask_server, args=(command_node,), daemon=True)
    flask_thread.start()
    try:
        executor = MultiThreadedExecutor()
        executor.add_node(command_node)
        executor.add_node(video_node)
        executor.spin()
    finally:
        command_node.destroy_node()
        video_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
