import heapq
import logging
import math
import os
import threading
import json
from std_msgs.msg import String 

try:
    import rclpy
    from rclpy.node import Node
    from nav_msgs.msg import OccupancyGrid, Path
    from geometry_msgs.msg import PointStamped, PoseStamped
    HAS_RCLPY = True
except Exception:
    HAS_RCLPY = False
    Node = object

    class OccupancyGrid:
        def __init__(self):
            self.header = None
            self.info = None
            self.data = []

    class Path:
        def __init__(self):
            self.header = None
            self.poses = []

    class Point:
        def __init__(self):
            self.x = 0.0
            self.y = 0.0
            self.z = 0.0

    class Quaternion:
        def __init__(self):
            self.x = 0.0
            self.y = 0.0
            self.z = 0.0
            self.w = 1.0

    class Pose:
        def __init__(self):
            self.position = Point()
            self.orientation = Quaternion()

    class PoseStamped:
        def __init__(self):
            self.header = None
            self.pose = Pose()

    class PointStamped:
        def __init__(self):
            self.header = None
            self.point = Point()


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class AStarPathNode(Node if HAS_RCLPY else object):
    """Plans a path from the map center to the exploration target."""

    def __init__(self):
        if HAS_RCLPY:
            super().__init__('astar_path')

        self.map_topic = os.environ.get('ASTAR_MAP_TOPIC', '/inflated_occupancy_grid')
        self.target_topic = os.environ.get('ASTAR_TARGET_TOPIC', '/explor_cell')
        self.position_topic = os.environ.get('ASTAR_POSITION_TOPIC', '/position')
        self.path_topic = os.environ.get('ASTAR_PATH_TOPIC', '/exploration_path')
        self.publish_hz = float(os.environ.get('ASTAR_PUBLISH_HZ', '2.0'))
        self.obstacle_threshold = int(os.environ.get('ASTAR_OBSTACLE_THRESHOLD', '50'))
        self.allow_diagonal = os.environ.get('ASTAR_ALLOW_DIAGONAL', '0') != '0'

        self._latest_map = None
        self._latest_target = None
        self._lock = threading.Lock()
        self._latest_position = {'x': 0.0, 'y': 0.0}

        if HAS_RCLPY:
            self.map_sub = self.create_subscription(OccupancyGrid, self.map_topic, self._on_map, 1)
            self.target_sub = self.create_subscription(PointStamped, self.target_topic, self._on_target, 1)
            self.position_sub = self.create_subscription(PointStamped, self.position_topic, self._on_position, 1)
            self.pub = self.create_publisher(Path, self.path_topic, 1)
            self.create_timer(1.0 / self.publish_hz, self._timer_cb)
        else:
            logger.info('rclpy not available: A* path node will not subscribe or publish')

    def _on_map(self, msg: OccupancyGrid):
        with self._lock:
            self._latest_map = msg

    def _on_target(self, msg: PointStamped):
        with self._lock:
            self._latest_target = msg

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

    def _timer_cb(self):
        with self._lock:
            grid = self._latest_map
            target = self._latest_target

        if grid is None or target is None:
            return

        path = self._plan_path(grid, target)
        if path is not None and HAS_RCLPY:
            self.pub.publish(path)

    def _plan_path(self, grid: OccupancyGrid, target: PointStamped):
        width = int(grid.info.width)
        height = int(grid.info.height)
        data = [int(value) for value in grid.data]
        print(f"Grid size: {width}x{height}, data length: {len(data)}")
        if width <= 0 or height <= 0 or len(data) < width * height:
            return None

        start = self._point_to_cell(grid, self._latest_position['x'], self._latest_position['y'])
        goal = (target.point.y, target.point.x)  # (row, col)
        if goal is None:
            return None

        if not self._is_inside(start, width, height) or not self._is_inside(goal, width, height):
            return None
        
        print(f"Planning path from {start} to {goal} in grid of size {width}x{height}")
        cells = self._astar(data, width, height, start, goal)
        if not cells:
            return None

        path = Path()
        path.header = grid.header
        if HAS_RCLPY:
            path.header.stamp = self.get_clock().now().to_msg()
        path.poses = [self._cell_to_pose(grid, row, col) for row, col in cells]
        return path

    def _astar(self, data, width: int, height: int, start: tuple, goal: tuple):
        frontier = []
        heapq.heappush(frontier, (0.0, start))
        came_from = {start: None}
        cost_so_far = {start: 0.0}

        while frontier:
            _, current = heapq.heappop(frontier)
            if current == goal:
                return self._reconstruct_path(came_from, current)

            for neighbor, step_cost in self._neighbors(current, width, height):
                if self._is_blocked(data, width, neighbor) and neighbor != goal:
                    continue

                new_cost = cost_so_far[current] + step_cost
                if neighbor not in cost_so_far or new_cost < cost_so_far[neighbor]:
                    cost_so_far[neighbor] = new_cost
                    priority = new_cost + self._heuristic(neighbor, goal)
                    heapq.heappush(frontier, (priority, neighbor))
                    came_from[neighbor] = current
        print(f"No path found from {start} to {goal}")
        return []

    def _neighbors(self, cell: tuple, width: int, height: int):
        row, col = cell
        offsets = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0)]
        if self.allow_diagonal:
            diagonal_cost = math.sqrt(2.0)
            offsets.extend([
                (-1, -1, diagonal_cost),
                (-1, 1, diagonal_cost),
                (1, -1, diagonal_cost),
                (1, 1, diagonal_cost),
            ])

        for d_row, d_col, cost in offsets:
            neighbor = (row + d_row, col + d_col)
            if self._is_inside(neighbor, width, height):
                yield neighbor, cost

    def _is_blocked(self, data, width: int, cell: tuple) -> bool:
        row, col = cell
        return int(data[row * width + col]) >= self.obstacle_threshold

    def _is_inside(self, cell: tuple, width: int, height: int) -> bool:
        row, col = cell
        return 0 <= row < height and 0 <= col < width

    def _heuristic(self, cell: tuple, goal: tuple) -> float:
        return math.hypot(cell[0] - goal[0], cell[1] - goal[1])

    def _reconstruct_path(self, came_from: dict, current: tuple):
        path = [current]
        while came_from[current] is not None:
            current = came_from[current]
            path.append(current)
        path.reverse()
        return path

    def _point_to_cell(self, grid: OccupancyGrid, x: float, y: float):
        try:
            resolution = float(grid.info.resolution)
            origin = grid.info.origin.position
            col = int(math.floor((float(x) - origin.x) / resolution))
            row = int(math.floor((float(y) - origin.y) / resolution))
            return row, col
        except Exception as e:
            try:
                self.get_logger().warning(f'Failed to convert target point to cell: {e}')
            except Exception:
                logger.warning(f'Failed to convert target point to cell: {e}')
            return None

    def _cell_to_pose(self, grid: OccupancyGrid, row: int, col: int):
        pose = PoseStamped()
        pose.header = grid.header

        resolution = float(grid.info.resolution)
        origin = grid.info.origin.position
        pose.pose.position.x = float(col)
        pose.pose.position.y = float(row)
        pose.pose.position.z = 0.0
        pose.pose.orientation.w = 1.0
        return pose


def main(args=None):
    if not HAS_RCLPY:
        print('rclpy not available; astar_path_node cannot run as a ROS node here.')
        return

    rclpy.init(args=args)
    node = AStarPathNode()
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
