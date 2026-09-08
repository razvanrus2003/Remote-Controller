import json
import logging
import math
import math
import os
import threading

from remote_control.astar_path_node import OccupancyGrid, PoseStamped

try:
    import rclpy
    from rclpy.node import Node
    from nav_msgs.msg import Path
    from std_msgs.msg import String
    HAS_RCLPY = True
except Exception:
    HAS_RCLPY = False
    Node = object

    class Path:
        def __init__(self):
            self.header = None
            self.poses = []

    class String:
        def __init__(self):
            self.data = ''


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class PathSplitterNode(Node if HAS_RCLPY else object):
    """Converts a planned path into a JSON list of real-world positions."""

    def __init__(self):
        if HAS_RCLPY:
            super().__init__('path_splitter')

        self.path_topic = os.environ.get('SPLITTER_PATH_TOPIC', '/exploration_path')
        self.positions_topic = os.environ.get('SPLITTER_POSITIONS_TOPIC', '/exploration_positions')
        self.position_topic = os.environ.get('SPLITTER_POSITION_TOPIC', '/inflated_occupancy_grid')
        self.publish_hz = float(os.environ.get('SPLITTER_PUBLISH_HZ', '2.0'))
        self.decimals = int(os.environ.get('SPLITTER_DECIMALS', '1'))
        self.turn_threshold_deg = float(os.environ.get("SPLITTER_TURN_THRESHOLD_DEG", "10.0"))

        self._latest_path = None
        self._lock = threading.Lock()

        if HAS_RCLPY:
            self.sub = self.create_subscription(Path, self.path_topic, self._on_path, 1)
            self.pub = self.create_publisher(String, self.positions_topic, 1)
            self.sub_grid = self.create_subscription(OccupancyGrid, self.position_topic, self._on_grid, 1)
            self.create_timer(1.0 / self.publish_hz, self._timer_cb)
        else:
            logger.info('rclpy not available: path splitter node will not subscribe or publish')

    def _on_path(self, msg: Path):
        with self._lock:
            self._latest_path = msg

    def _on_grid(self, msg: OccupancyGrid):
        with self._lock:
            self._latest_grid = msg

    def _timer_cb(self):
        with self._lock:
            path = self._latest_path

        if path is None:
            return

        msg = String()
        msg.data = self._path_to_json(path)
        if HAS_RCLPY:
            self.pub.publish(msg)

    def _path_to_json(self, path: Path) -> str:
        if len(path.poses) < 2:
            list = []
            for pose_stamped in path.poses:
                pose = pose_stamped.pose.position
                list.append(self._cell_to_pose(self._latest_grid, pose.y, pose.x))
            return json.dumps({"positions": list})

        turn_points = []

        if len(path.poses) == 2:
            first_pose = path.poses[1].pose.position
            turn_points.append(self._cell_to_pose(self._latest_grid, first_pose.y, first_pose.x))
            return json.dumps({"positions": turn_points})

        previous_heading = None

        for i in range(len(path.poses) - 1):
            p1 = path.poses[i].pose.position
            p2 = path.poses[i + 1].pose.position

            dx = float(p2.x) - float(p1.x)
            dy = float(p2.y) - float(p1.y)

            heading = math.atan2(dy, dx)

            if previous_heading is not None:

                # Normalize angle difference to [-pi, pi]
                angle_diff = heading - previous_heading
                angle_diff = math.atan2(
                    math.sin(angle_diff),
                    math.cos(angle_diff)
                )

                angle_diff_deg = math.degrees(angle_diff)

                if abs(angle_diff_deg) >= self.turn_threshold_deg:
                    turn_points.append(self._cell_to_pose(self._latest_grid, p2.y, p2.x))

            previous_heading = heading
        
        turn_points.append(self._cell_to_pose(self._latest_grid, path.poses[-1].pose.position.y, path.poses[-1].pose.position.x))

        return json.dumps({"positions": turn_points})
    

    def _cell_to_pose(self, grid: OccupancyGrid, row: int, col: int):
        resolution = float(grid.info.resolution)
        origin = grid.info.origin.position
        x = origin.x + (col + 0.5) * resolution
        y = origin.y + (row + 0.5) * resolution
        
        return [x, y]


def main(args=None):
    if not HAS_RCLPY:
        print('rclpy not available; path_splitter_node cannot run as a ROS node here.')
        return

    rclpy.init(args=args)
    node = PathSplitterNode()
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
