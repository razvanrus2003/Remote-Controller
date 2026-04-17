import rclpy
from rclpy.node import Node
from std_msgs.msg import Int16MultiArray

import sys
import time
import termios
import tty
from contextlib import contextmanager

try:
    import pygame
except ImportError:
    pygame = None


class KeyboardPublisher(Node):
    def __init__(self):
        super().__init__('keyboard_publisher')
        self.publisher = self.create_publisher(Int16MultiArray, '/motor_speeds', 10)
        self.left_speed = 0
        self.right_speed = 0
        self.speed_step = 20
        self.max_speed = 100
        self.publish_delay = 0.1
        self.deadzone = 0.12
        self.controller = None
        self.mode = 'keyboard'

        self._init_controller()
        if self.mode == 'controller':
            self.get_logger().info(
                'Xbox controller detected. Left stick drives the robot, A stops, B quits.'
            )
        else:
            self.get_logger().info(
                'Keyboard mode active. Keys: w/s forward/back, a/d turn, x stop, +/-, q quit.'
            )

    def _init_controller(self):
        if pygame is None:
            self.get_logger().warning('pygame is not installed, using keyboard mode only.')
            return

        pygame.init()
        pygame.joystick.init()

        joystick_count = pygame.joystick.get_count()
        if joystick_count == 0:
            self.get_logger().info('No game controller found. Falling back to keyboard mode.')
            return

        self.controller = pygame.joystick.Joystick(0)
        self.controller.init()
        self.mode = 'controller'
        self.get_logger().info(f'Using controller: {self.controller.get_name()}')

    def publish_speeds(self, left_speed: int, right_speed: int):
        left_speed = int(max(min(left_speed, self.max_speed), -self.max_speed))
        right_speed = int(max(min(right_speed, self.max_speed), -self.max_speed))

        msg = Int16MultiArray()
        msg.data = [left_speed, right_speed]
        self.publisher.publish(msg)
        self.left_speed = left_speed
        self.right_speed = right_speed
        self.get_logger().info(f'Published motor speeds: [{left_speed}, {right_speed}]')
        if self.publish_delay > 0:
            time.sleep(self.publish_delay)

    def publish_from_sticks(self, left_stick_y: float, right_stick_y: float):
        if abs(left_stick_y) < self.deadzone:
            left_stick_y = 0.0
        if abs(right_stick_y) < self.deadzone:
            right_stick_y = 0.0

        left_speed = int(round(-left_stick_y * self.max_speed))
        right_speed = int(round(-right_stick_y * self.max_speed))
        self.publish_speeds(left_speed, right_speed)

    def stop(self):
        self.publish_speeds(0, 0)

    def move_forward(self):
        self.publish_speeds(self.left_speed + self.speed_step, self.right_speed + self.speed_step)

    def move_backward(self):
        self.publish_speeds(self.left_speed - self.speed_step, self.right_speed - self.speed_step)

    def turn_left(self):
        self.publish_speeds(self.left_speed - self.speed_step, self.right_speed + self.speed_step)

    def turn_right(self):
        self.publish_speeds(self.left_speed + self.speed_step, self.right_speed - self.speed_step)

    def increase_speed(self):
        self.speed_step = min(self.speed_step + 5, self.max_speed)
        self.get_logger().info(f'Speed step increased to {self.speed_step}')

    def decrease_speed(self):
        self.speed_step = max(self.speed_step - 5, 5)
        self.get_logger().info(f'Speed step decreased to {self.speed_step}')

    def show_help(self):
        self.get_logger().info('Controls: w forward, s backward, a left, d right, x stop, + faster, - slower, q quit')

    def _controller_button_pressed(self, button_index: int) -> bool:
        return bool(self.controller and self.controller.get_numbuttons() > button_index and self.controller.get_button(button_index))

    def run_controller_loop(self):
        self.publish_speeds(0, 0)

        while rclpy.ok():
            try:
                pygame.event.pump()
            except KeyboardInterrupt:
                break

            left_stick_y = self.controller.get_axis(1)
            right_stick_y = self.controller.get_axis(4)
            self.publish_from_sticks(left_stick_y, right_stick_y)

            if self._controller_button_pressed(0):
                self.stop()
            if self._controller_button_pressed(1):
                self.stop()
                break

            rclpy.spin_once(self, timeout_sec=0.02)

    def run_keyboard_loop(self):
        self.show_help()
        self.stop()

        while rclpy.ok():
            try:
                command = read_key()
            except (EOFError, KeyboardInterrupt):
                break

            if not command:
                continue

            if command in ('q', '\x03'):
                break
            if command == 'x':
                self.stop()
                continue
            if command == 'w':
                self.move_forward()
                continue
            if command == 's':
                self.move_backward()
                continue
            if command == 'a':
                self.turn_left()
                continue
            if command == 'd':
                self.turn_right()
                continue
            if command == '+':
                self.increase_speed()
                continue
            if command == '-':
                self.decrease_speed()
                continue
            if command == 'h':
                self.show_help()
                continue

            self.get_logger().info('Unknown key. Press h for help.')


@contextmanager
def raw_terminal_mode():
    if not sys.stdin.isatty():
        yield
        return

    fd = sys.stdin.fileno()
    original_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original_settings)


def read_key():
    if not sys.stdin.isatty():
        return input('Command> ').strip().lower()[:1]

    return sys.stdin.read(1).lower()


def main(args=None):
    rclpy.init(args=args)
    node = KeyboardPublisher()
    try:
        if node.mode == 'controller':
            node.run_controller_loop()
        else:
            with raw_terminal_mode():
                node.run_keyboard_loop()
    except KeyboardInterrupt:
        node.get_logger().info('Keyboard input interrupted.')
    finally:
        node.destroy_node()
        rclpy.shutdown()
