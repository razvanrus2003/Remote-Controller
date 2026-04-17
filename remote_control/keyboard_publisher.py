import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32


class KeyboardPublisher(Node):
    def __init__(self):
        super().__init__('keyboard_publisher')
        self.publisher = self.create_publisher(Float32, '/motor_power', 10)
        self.current_power = 0.0
        self.get_logger().info('Keyboard publisher started. Use "set <value>", "inc", "dec", "stop", or "exit".')

    def publish_power(self, power: float):
        msg = Float32()
        msg.data = float(power)
        self.publisher.publish(msg)
        self.get_logger().info(f'Published motor power: {msg.data:.3f}')
        self.current_power = msg.data

    def run_command_loop(self):
        while rclpy.ok():
            try:
                command = input('Command> ').strip().lower()
            except EOFError:
                break

            if command == 'exit':
                break
            if command == 'stop':
                self.publish_power(0.0)
                continue
            if command == 'inc':
                self.publish_power(min(self.current_power + 0.1, 1.0))
                continue
            if command == 'dec':
                self.publish_power(max(self.current_power - 0.1, -1.0))
                continue
            if command.startswith('set '):
                try:
                    value = float(command.split(' ', 1)[1])
                    self.publish_power(max(min(value, 1.0), -1.0))
                except ValueError:
                    self.get_logger().warning('Invalid set value. Use set <float> between -1.0 and 1.0.')
                continue

            self.get_logger().info('Commands: set <value>, inc, dec, stop, exit')


def main(args=None):
    rclpy.init(args=args)
    node = KeyboardPublisher()
    try:
        node.run_command_loop()
    except KeyboardInterrupt:
        node.get_logger().info('Keyboard input interrupted.')
    finally:
        node.destroy_node()
        rclpy.shutdown()
