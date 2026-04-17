import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class VideoSubscriber(Node):
    def __init__(self):
        super().__init__('video_subscriber')
        self.subscription = self.create_subscription(
            String,
            '/camera_feed',
            self.on_frame_received,
            10,
        )
        self.get_logger().info('Video subscriber started. Waiting for camera frames...')

    def on_frame_received(self, msg: String):
        self.get_logger().info(f'Received camera frame placeholder: {msg.data}')


def main(args=None):
    rclpy.init(args=args)
    node = VideoSubscriber()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('Shutting down video subscriber...')
    finally:
        node.destroy_node()
        rclpy.shutdown()
