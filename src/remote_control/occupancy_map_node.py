import os
import time
import json
import threading
import logging
import math

from sympy import rad

try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String, Header
    from nav_msgs.msg import OccupancyGrid, MapMetaData
    from geometry_msgs.msg import Pose
    from geometry_msgs.msg import Point, Quaternion
    HAS_RCLPY = True
except Exception:
    # Allow importing this module outside of ROS for inspection/testing
    HAS_RCLPY = False
    Node = object
    class String:
        def __init__(self):
            self.data = ''
    class Header:
        def __init__(self):
            self.stamp = None
            self.frame_id = ''
    class MapMetaData:
        def __init__(self):
            self.map_load_time = None
            self.resolution = 0.0
            self.width = 0
            self.height = 0
            self.origin = None
    class OccupancyGrid:
        def __init__(self):
            self.header = Header()
            self.info = MapMetaData()
            self.data = []

import numpy as np

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class OccupancyMapNode(Node if HAS_RCLPY else object):
    """Simple node that converts /obstacle JSON messages into an OccupancyGrid.

    Behavior:
    - Subscribes to `/obstacle` (std_msgs/String, JSON payload produced by VideoMlNode).
    - Maintains an internal 2D grid of occupancy values (-1 unknown, 0 free, 100 occupied).
    - When an obstacle message arrives, marks a frontal region as occupied proportional to `confidence`.
    - Publishes `nav_msgs/OccupancyGrid` at a configurable rate and decays old occupancy over time.
    """

    def __init__(self):
        super().__init__('occupancy_map')

        # Configurable params via env
        self.frame_id = os.environ.get('OCCUPANCY_FRAME', 'map')
        self.resolution = float(os.environ.get('OCCUPANCY_RESOLUTION', '300'))  # millimeters per cell
        self.map_width = int(os.environ.get('OCCUPANCY_WIDTH', '7'))
        self.map_height = int(os.environ.get('OCCUPANCY_HEIGHT', '7'))
        # decay: occupancy points reduce by this amount per second
        self.decay_per_sec = float(os.environ.get('OCCUPANCY_DECAY_PER_SEC', '0'))
        # TTL for entries (seconds) after which they revert to unknown
        self.entry_ttl = float(os.environ.get('OCCUPANCY_ENTRY_TTL', '20.0'))

        # internal grid stores occupancy (0..100) and timestamps of last update; -1 means unknown
        self._grid = np.full((self.map_height, self.map_width), -1, dtype=np.int8)
        self._timestamps = np.zeros((self.map_height, self.map_width), dtype=np.float64)
        self._lock = threading.Lock()

        # publishers / subscribers
        if HAS_RCLPY:
            # keep legacy /obstacle
            self.sub = self.create_subscription(String, '/obstacle', self._on_obstacle, 1)
            # new subscription for robot pose
            self.pos_sub = self.create_subscription(String, '/position', self._on_position, 1)
            self.pub = self.create_publisher(OccupancyGrid, '/occupancy_grid', 1)
            # periodic timer to publish and age grid
            pub_rate = float(os.environ.get('OCCUPANCY_PUBLISH_HZ', '2.0'))
            self.create_timer(1.0 / pub_rate, self._timer_cb)
        else:
            logger.info('rclpy not available: node will not subscribe or publish')

        # robot pose (updated from /position)
        self.robot_x = 0.0
        self.robot_y = 0.0
        self.robot_ang = 0.0

    def _coord_to_cell(self, x_m: float, y_m: float):
        """Convert robot-relative coordinates (x forward, y right) to grid cell indices."""
        col = int(round(self.map_width // 2 - y_m / self.resolution))
        row = int(round(self.map_height // 2 + x_m / self.resolution))
        if row < 0 or row >= self.map_height or col < 0 or col >= self.map_width:
            return None
        return row, col
    

    def _get_front_cells(self, robot_cell: tuple, robot_angle: float):
        """Get a list of grid cell indices in a wedge in front of the robot."""
        cells = []
        
        for r in range(1 , 2):
            row = robot_cell[0] - round(math.sin(rad(robot_angle))) * r
            col = robot_cell[1] + round(math.cos(rad(robot_angle))) * r

            row = int(round(row))
            col = int(round(col))

            cells.append((row, col))
            # cells.append((row, robot_cell[1]))
            # cells.append((robot_cell[0], col))
        return cells

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
        blocked = bool(state.get('blocked', False))
        obstacle_median = state.get('metrics', {}).get('obstacle_median', 0.0)
        floor_median = 1 - state.get('metrics', {}).get('floor_median', 0.0)

        if blocked:
            confidence = 100.0
        else:
            confidence = max(obstacle_median, floor_median) * 100.0  # scale to 0..100

        robot_cell = self._coord_to_cell(self.robot_x, self.robot_y)
        if robot_cell is None:
            self.get_logger().warning('Robot position is outside the map bounds')
            return
        cells = self._get_front_cells(robot_cell, self.robot_ang)

        for row, col in cells:
            self._mark_cell(row, col, confidence)


    def _parse_position_string(self, data: str) -> dict:
        result = {}
        for part in data.split(','):
            part = part.strip()
            if '=' not in part:
                continue
            key, _, val = part.partition('=')
            result[key.strip()] = val.strip()
        return result

    def _on_position(self, msg: String):
        try:
            state = self._parse_position_string(msg.data)
        except Exception as e:
            logger.warning(f'Failed to parse position: {e}')
            return

        with self._lock:
            try:
                self.robot_x   = float(state.get('robot_x',   self.robot_x))
                self.robot_y   = float(state.get('robot_y',   self.robot_y))
                self.robot_ang = float(state.get('robot_ang', self.robot_ang))
            except Exception:
                pass

    def _mark_cell(self, row: int, col: int, value: int = 100):
        now = time.time()

        if (row < 0 or row >= self.map_height or col < 0 or col >= self.map_width):
            return
        last_value = self._grid[row, col]
        last_time = self._timestamps[row, col]
        with self._lock:
            if (last_value == 100 ) and (now - last_time > 10.0):
                self._grid[row, col] = int(value)
                self._timestamps[row, col] = now
            elif (last_value < 100):
                self._grid[row, col] = int(value)
                self._timestamps[row, col] = now

    def _age_and_publish(self):
        now = time.time()
        # with self._lock:
        #     mask = self._timestamps > 0
        #     if mask.any():
        #         expired = mask & ((now - self._timestamps) > self.entry_ttl)
        #         self._grid[expired] = -1
        #         self._timestamps[expired] = 0.0

        # build OccupancyGrid
        grid = OccupancyGrid()
        try:
            grid.header = Header()
            try:
                grid.header.stamp = self.get_clock().now().to_msg()
            except Exception:
                pass
            grid.header.frame_id = self.frame_id
        except Exception:
            # in non-ROS environment, Header may be simple class
            grid.header = Header()
            grid.header.frame_id = self.frame_id

        info = MapMetaData()
        info.resolution = float(self.resolution)
        info.width = int(self.map_width)
        info.height = int(self.map_height)
        # origin in the middle of the grid, facing forward along +x
        try:
            p = Pose()
            p.position.x = - (self.map_width * self.resolution) / 2.0
            p.position.y = - (self.map_height * self.resolution) / 2.0
            p.position.z = 0.0
            p.orientation = Quaternion()
            p.orientation.x = 0.0
            p.orientation.y = 0.0
            p.orientation.z = 0.0
            p.orientation.w = 1.0
            info.origin = p
        except Exception:
            info.origin = None

        grid.info = info

        # Flatten grid row-major with -1,0..100
        with self._lock:
            flat = self._grid.flatten(order='C').tolist()
        # nav_msgs expects int8 list; ensure Python ints
        grid.data = [int(x) for x in flat]

        if HAS_RCLPY:
            try:
                self.pub.publish(grid)
            except Exception as e:
                try:
                    self.get_logger().warning(f'Failed to publish occupancy grid: {e}')
                except Exception:
                    logger.warning(f'Failed to publish occupancy grid: {e}')
        else:
            logger.debug('Aged grid (non-ROS mode), not published')

    def _timer_cb(self):
        try:
            self._age_and_publish()
        except Exception as e:
            try:
                self.get_logger().warning(f'Error in occupancy timer: {e}')
            except Exception:
                logger.warning(f'Error in occupancy timer: {e}')


def main(args=None):
    if not HAS_RCLPY:
        print('rclpy not available; occupancy_map_node cannot run as a ROS node here.')
        return

    rclpy.init(args=args)
    node = OccupancyMapNode()
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
