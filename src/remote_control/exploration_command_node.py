import json
import logging
import math
import os
import threading
import time

try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import Bool, String
    try:
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    except Exception:
        DurabilityPolicy = None
        QoSProfile = None
        ReliabilityPolicy = None
    HAS_RCLPY = True
except Exception:
    HAS_RCLPY = False
    Node = object

    class Bool:
        def __init__(self):
            self.data = False

    class String:
        def __init__(self):
            self.data = ''

    DurabilityPolicy = None
    QoSProfile = None
    ReliabilityPolicy = None


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class ExplorationCommandNode(Node if HAS_RCLPY else object):
    """Sends exploration positions to /command one at a time when enabled."""

    def __init__(self):
        if HAS_RCLPY:
            super().__init__('exploration_command')

        self.positions_topic = os.environ.get('EXPLORATION_COMMAND_POSITIONS_TOPIC', '/exploration_positions')
        self.position_topic = os.environ.get('EXPLORATION_COMMAND_POSITION_TOPIC', '/position')
        self.enabled_topic = os.environ.get('EXPLORATION_COMMAND_ENABLED_TOPIC', '/exploration_sequence_enabled')
        self.command_topic = os.environ.get('EXPLORATION_COMMAND_TOPIC', '/command')
        self.obstacle_topic = os.environ.get('EXPLORATION_COMMAND_OBSTACLE_TOPIC', '/obstacle')
        # Hardware has a 30mm tolerance from the target position
        self.arrival_threshold = float(os.environ.get('EXPLORATION_ARRIVAL_THRESHOLD', '100.0'))
        self.publish_hz = float(os.environ.get('EXPLORATION_COMMAND_HZ', '.20'))
        self.min_command_interval_sec = float(os.environ.get('EXPLORATION_COMMAND_MIN_INTERVAL_SEC', '0.5'))

        self.blocked = False
        self.command = None
        self._enabled = False
        self._positions = []
        self._positions_signature = None
        self._current_index = 0
        self._current_target = None
        self._latest_position = None
        self._last_command_at = 0.0
        self._lock = threading.Lock()

        if HAS_RCLPY:
            settings_qos = self._settings_qos()
            self.enabled_sub = self.create_subscription(Bool, self.enabled_topic, self._on_enabled, 1)
            self.positions_sub = self.create_subscription(String, self.positions_topic, self._on_positions, 1)
            self.position_sub = self.create_subscription(String, self.position_topic, self._on_position, 1)
            self.obstacle_sub = self.create_subscription(String, self.obstacle_topic, self._on_obstacle, 1)
            self.command_pub = self.create_publisher(String, self.command_topic, 1)
            self.create_timer(1.0 / self.publish_hz, self._timer_cb)
        else:
            logger.info('rclpy not available: exploration command node will not subscribe or publish')

    def _settings_qos(self):
        if QoSProfile is None:
            return 1

        qos = QoSProfile(depth=1)
        if DurabilityPolicy is not None:
            qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        if ReliabilityPolicy is not None:
            qos.reliability = ReliabilityPolicy.RELIABLE
        return qos

    def _on_obstacle(self, msg: String):
        try:
            state = json.loads(msg.data)
        except Exception as e:
            try:
                self.get_logger().warning(f'Invalid JSON on /obstacle: {e}')
            except Exception:
                logger.warning(f'Invalid JSON on /obstacle: {e}')
            return

        # Extract key fields with safe fallbacks
        self.blocked = bool(state.get('blocked', False))
        if self.blocked:
            self._log_info('Exploration command sequence blocked by obstacle')
            self._current_target = None
            #Stop command
            self._publish_command('M,0,0')  # Send a stop command to halt the robot
            time.sleep(0.5)  # Give time for the stop command to be processed

            self._publish_command('M,-0.7,-0.7')
            time.sleep(0.4)  # Give time for the stop command to be processed
            self._publish_command('M,0,0')  # Send a stop command to halt the robot
            self._positions = []  # Clear the positions to prevent further movement
            self._current_index = 0
            self._current_target = None
            time.sleep(1)  # Give time for the stop command to be processed
        pass

    def _on_enabled(self, msg: Bool):
        with self._lock:
            was_enabled = self._enabled
            self._enabled = bool(msg.data)
            if self._enabled and not was_enabled:
                self._current_index = 0
                self._current_target = None
                self._last_command_at = 0.0
            elif not self._enabled:
                self._current_target = None

        self._log_info(f'Exploration command sequence enabled={bool(msg.data)}')

    def _on_positions(self, msg: String):

        if (self._current_index < len(self._positions)) and (self._current_target is not None) and (not self._has_arrived_locked(self._current_target)):
            self._log_info(str(self._current_index < len(self._positions)) + " " + str(self._current_target) + " " + str(self._has_arrived_locked(self._current_target)) + " " + str(self._latest_position))
            self._log_info('Ignoring new exploration positions because the current target has not been reached yet')
            return
        try:
            positions = self._parse_positions(msg.data)
            signature = self._positions_signature_for(positions)
        except Exception as e:
            self._log_warning(f'Invalid exploration positions payload: {e}')
            return

        with self._lock:
            if signature == self._positions_signature:
                return

            self._positions = positions
            self._positions_signature = signature
            self._current_index = 0
            self._current_target = None
            self._last_command_at = 0.0

    def _on_position(self, msg: String):
        try:
            position = self._parse_position(msg.data)
        except Exception as e:
            self._log_warning(f'Invalid position payload: {e}')
            return

        if position is None:
            return

        with self._lock:
            self._latest_position = position

    def _timer_cb(self):
        # command = None
        with self._lock:
            if not self._enabled or not self._positions:
                return

            if self._current_target is None:
                self.command = self._next_command_locked()
            elif self._has_arrived_locked(self._current_target):
                self._current_index += 1
                if self._current_index < len(self._positions):
                    self.command = self._next_command_locked()
                else:
                    self._log_info('Exploration command sequence completed')

        if self.command is not None:
            self._publish_command(self.command)

    def _next_command_locked(self):
        now = time.monotonic()
        if now - self._last_command_at < self.min_command_interval_sec:
            return None

        if self._current_index >= len(self._positions):
            return None

        target = self._positions[self._current_index]
        self._current_target = target
        self._last_command_at = now
        return f'P,{target["x"]:g},{target["y"]:g}'

    def _has_arrived_locked(self, target: dict) -> bool:
        if self.blocked:
            return True
        if self._latest_position is None:
            return False

        dx = self._latest_position['x'] - target['x']
        dy = self._latest_position['y'] - target['y']
        return abs(dx) <= self.arrival_threshold and abs(dy) <= self.arrival_threshold

    def _publish_command(self, command: str):
        msg = String()
        msg.data = command
        if HAS_RCLPY:
            self.command_pub.publish(msg)
        self._log_info(f'Published exploration command: {command}')

    def _parse_positions(self, payload: str):
        print(f"Parsing positions from payload: {payload}")
        data = json.loads(payload)
        raw_positions = data.get('positions') if isinstance(data, dict) else data
        if not isinstance(raw_positions, list):
            raise ValueError('expected JSON object with positions list or a list')

        positions = []
        for item in raw_positions:
            if not isinstance(item, list):
                continue
            x = item[0]
            y = item[1]
            if x is None or y is None:
                continue
            positions.append({'x': float(x), 'y': float(y)})
        print(f"Parsed positions: {positions}")
        return positions

    def _positions_signature_for(self, positions):
        return tuple((round(point['x'], 3), round(point['y'], 3)) for point in positions)

    def _parse_position(self, payload: str):
        payload = payload.strip()
        if not payload:
            return None

        if payload.startswith('{'):
            return self._parse_position_object(json.loads(payload))

        values = {}
        for part in payload.split(','):
            key, sep, value = part.partition('=')
            if sep:
                values[key.strip()] = value.strip()
        return self._parse_position_object(values)

    def _parse_position_object(self, data):
        if not isinstance(data, dict):
            return None

        nested = data.get('position')
        if isinstance(nested, dict):
            nested_position = self._parse_position_object(nested)
            if nested_position is not None:
                return nested_position
        if isinstance(nested, str):
            return self._parse_position(nested)

        x = data.get('robot_x', data.get('x'))
        y = data.get('robot_y', data.get('y'))
        if x is None or y is None:
            return None
        return {'x': float(x), 'y': float(y)}

    def _log_info(self, message: str):
        try:
            self.get_logger().info(message)
        except Exception:
            logger.info(message)

    def _log_warning(self, message: str):
        try:
            self.get_logger().warning(message)
        except Exception:
            logger.warning(message)


def main(args=None):
    if not HAS_RCLPY:
        print('rclpy not available; exploration_command_node cannot run as a ROS node here.')
        return

    rclpy.init(args=args)
    node = ExplorationCommandNode()
    try:
        rclpy.spin(node)
    finally:
        try:
            node.destroy_node()
        except Exception:
            pass
        rclpy.shutdown()


if __name__ == '__main__':
    main()
