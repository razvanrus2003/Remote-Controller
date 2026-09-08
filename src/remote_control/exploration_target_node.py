import json
import logging
import math
import os
import random
import threading
from std_msgs.msg import String

try:
    import rclpy
    from rclpy.node import Node
    from nav_msgs.msg import OccupancyGrid
    from geometry_msgs.msg import PointStamped
    HAS_RCLPY = True
except Exception:
    HAS_RCLPY = False
    Node = object

    class OccupancyGrid:
        def __init__(self):
            self.header = None
            self.info = None
            self.data = []

    class Point:
        def __init__(self):
            self.x = 0.0
            self.y = 0.0
            self.z = 0.0

    class PointStamped:
        def __init__(self):
            self.header = None
            self.point = Point()


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class ExplorationTargetNode(Node if HAS_RCLPY else object):
    """Publishes the closest unexplored cell to the map center."""

    def __init__(self):
        if HAS_RCLPY:
            super().__init__('exploration_target')

        self.map_topic = os.environ.get('EXPLORATION_MAP_TOPIC', '/occupancy_grid')
        self.position_topic = os.environ.get('EXPLORATION_POSITION_TOPIC', '/position')
        self.target_topic = os.environ.get('EXPLORATION_TARGET_TOPIC', '/explor_cell')
        self.publish_hz = float(os.environ.get('EXPLORATION_PUBLISH_HZ', '1.0'))

        self._latest_map = None
        self._lock = threading.Lock()
        self._latest_position = {'x': 0.0, 'y': 0.0}
        self._lastest_target_cell = None

        if HAS_RCLPY:
            self.sub = self.create_subscription(OccupancyGrid, self.map_topic, self._on_map, 1)
            self.position_sub = self.create_subscription(PointStamped, self.position_topic, self._on_position, 1)
            self.pub = self.create_publisher(PointStamped, self.target_topic, 1)
            self.create_timer(1.0 / self.publish_hz, self._timer_cb)
        else:
            logger.info('rclpy not available: exploration target node will not subscribe or publish')

    def _on_map(self, msg: OccupancyGrid):
        with self._lock:
            self._latest_map = msg

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

        if grid is None:
            return

        target_cell = self._select_target_cell(grid)
        if target_cell is None:
            return
        
        target_cell_msg = PointStamped()
        target_cell_msg.header = grid.header
        target_cell_msg.point.x = float(target_cell[1])
        target_cell_msg.point.y = float(target_cell[0])
        target_cell_msg.point.z = 0.0

        if HAS_RCLPY:
            self.pub.publish(target_cell_msg)

    def _point_to_cell(self, grid: OccupancyGrid, x: float, y: float):
        origin_x = grid.info.origin.position.x
        origin_y = grid.info.origin.position.y
        resolution = grid.info.resolution

        col = int((x - origin_x) / resolution)
        row = int((y - origin_y) / resolution)

        if 0 <= col < grid.info.width and 0 <= row < grid.info.height:
            return row, col
        return None

    def _is_inside(self, row: int, col: int, width: int, height: int) -> bool:
        return 0 <= row < height and 0 <= col < width

    def _inspect_cell(self, grid: OccupancyGrid, row: int, col: int) -> bool:
        if not self._is_inside(row, col, grid.info.width, grid.info.height):
            return False
        index = row * grid.info.width + col
        if index < 0 or index >= len(grid.data):
            return False
        return grid.data[index] == -1  # unexplored

    def _select_target_cell(self, grid: OccupancyGrid):
        print("Selecting target cell...")
        # robot_cell = self._point_to_cell(grid, self._latest_position['x'], self._latest_position['y'])
        # if robot_cell is None:
        #     return None
        # robot_row, robot_col = robot_cell
        cells = []
        for row in range(0, grid.info.height):
            for col in range(0, grid.info.width):
                if grid.data[row * grid.info.width + col] == -1:  # unexplored
                    cells.append((row, col))
                    
        #         cell_row = robot_row + row
        #         cell_col = robot_col + col
        #         if self._inspect_cell(grid, cell_row, cell_col):
        #             return cell_row, cell_col
                
        #         cell_row = robot_row - row
        #         cell_col = robot_col - col
        #         if self._inspect_cell(grid, cell_row, cell_col):
        #             return cell_row, cell_col
                
        #         cell_row = robot_row + row
        #         cell_col = robot_col - col
        #         if self._inspect_cell(grid, cell_row, cell_col):
        #             return cell_row, cell_col
                
        #         cell_row = robot_row - row
        #         cell_col = robot_col + col
        #         if self._inspect_cell(grid, cell_row, cell_col):
        #             return cell_row, cell_col
        row, col = random.choice(cells)
        if self._inspect_cell(grid, row, col):
            self._lastest_target_cell = (row, col)
            return row, col
        return None

    def _cell_distance(self, row: int, col: int, center_row: int, center_col: int) -> float:
        return math.hypot(row - center_row, col - center_col)


def main(args=None):
    if not HAS_RCLPY:
        print('rclpy not available; exploration_target_node cannot run as a ROS node here.')
        return

    rclpy.init(args=args)
    node = ExplorationTargetNode()
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
