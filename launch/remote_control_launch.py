from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch_ros.actions import Node
import os


def generate_launch_description():
    # run npm build/dev in the workspace `frontend` directory — assume launch is run from repo root
    cwd = os.getcwd()
    venv_python = os.path.join(cwd, '.venv', 'bin', 'python')
    frontend_cmd = [
        'bash',
        '-lc',
        'cd frontend && npm install --silent && npm run build --silent && npm run dev'
    ]
    return LaunchDescription([
        ExecuteProcess(cmd=frontend_cmd, cwd=cwd, output='screen'),
        # web_video_server exposes ROS image topics over HTTP (MJPEG/stream)
        Node(
            package='web_video_server',
            executable='web_video_server',
            name='web_video_server',
            output='screen',
            parameters=[{
                'port': int(os.environ.get('WEB_VIDEO_PORT', '8080')),
                # bind to all interfaces by default so remote clients can connect
                'address': os.environ.get('WEB_VIDEO_ADDRESS', '0.0.0.0'),
            }],
        ),
        Node(
            package='remote_control',
            executable='command_api',
            name='remote_command_api',
            output='screen',
        ),
        ExecuteProcess(
            # Ensure ROS environment is sourced before invoking the venv python
            cmd=['bash', '-lc', 'source /opt/ros/jazzy/setup.bash && ' + venv_python + ' -m remote_control.video_ml'],
            cwd=cwd,
            output='screen',
            env=dict(os.environ, DEPTH_BACKEND='fast'),
        ),
    ])
