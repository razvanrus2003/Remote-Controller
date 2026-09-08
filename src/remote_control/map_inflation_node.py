import logging
import math
import os
import threading

try:
    import rclpy
    from rclpy.node import Node
    from nav_msgs.msg import OccupancyGrid
    HAS_RCLPY = True
except Exception:
    HAS_RCLPY = False
    Node = object

    class OccupancyGrid:
        def __init__(self):
            self.header = None
            self.info = None
            self.data = []


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class MapInflationNode(Node if HAS_RCLPY else object):
    """Inflates occupied cells so path planning keeps distance from obstacles."""

    def __init__(self):
        if HAS_RCLPY:
            super().__init__('map_inflation')

        self.map_topic = os.environ.get('INFLATION_MAP_TOPIC', '/occupancy_grid')
        self.inflated_topic = os.environ.get('INFLATION_OUTPUT_TOPIC', '/inflated_occupancy_grid')
        self.publish_hz = float(os.environ.get('INFLATION_PUBLISH_HZ', '2.0'))
        self.obstacle_threshold = int(os.environ.get('INFLATION_OBSTACLE_THRESHOLD', '50'))
        self.inflation_radius_cells = int(os.environ.get('INFLATION_RADIUS_CELLS', '1'))

        self._latest_map = None
        self._lock = threading.Lock()

        if HAS_RCLPY:
            self.sub = self.create_subscription(OccupancyGrid, self.map_topic, self._on_map, 1)
            self.pub = self.create_publisher(OccupancyGrid, self.inflated_topic, 1)
            self.create_timer(1.0 / self.publish_hz, self._timer_cb)
        else:
            logger.info('rclpy not available: map inflation node will not subscribe or publish')

    def _on_map(self, msg: OccupancyGrid):
        with self._lock:
            self._latest_map = msg

    def _timer_cb(self):
        with self._lock:
            grid = self._latest_map

        if grid is None:
            return

        inflated = self._inflate_grid(grid)
        if inflated is not None and HAS_RCLPY:
            self.pub.publish(inflated)

    def _inflate_grid(self, grid: OccupancyGrid):
        width = int(grid.info.width)
        height = int(grid.info.height)
        data = [int(value) for value in grid.data]

        if width <= 0 or height <= 0 or len(data) < width * height:
            return None

        inflated_data = data[:width * height]
        radius = max(0, self.inflation_radius_cells)
        obstacle_cells = []

        for row in range(height):
            for col in range(width):
                value = data[row * width + col]
                if value >= self.obstacle_threshold:
                    obstacle_cells.append((row, col))

        for row, col in obstacle_cells:
            for neighbor_row, neighbor_col in self._cells_inside_radius(row, col, width, height, radius):
                inflated_data[neighbor_row * width + neighbor_col] = 100

        inflated = OccupancyGrid()
        inflated.header = grid.header
        inflated.info = grid.info
        inflated.data = inflated_data
        return inflated

    def _cells_inside_radius(self, row: int, col: int, width: int, height: int, radius: int):
        if radius <= 0:
            yield row, col
            return

        for d_row in range(-radius, radius + 1):
            for d_col in range(-radius, radius + 1):
                if math.hypot(d_row, d_col) > radius:
                    continue

                neighbor_row = row + d_row
                neighbor_col = col + d_col
                if 0 <= neighbor_row < height and 0 <= neighbor_col < width:
                    yield neighbor_row, neighbor_col


def main(args=None):
    if not HAS_RCLPY:
        print('rclpy not available; map_inflation_node cannot run as a ROS node here.')
        return

    rclpy.init(args=args)
    node = MapInflationNode()
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
