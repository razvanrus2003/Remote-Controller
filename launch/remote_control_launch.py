from launch import LaunchDescription
from launch.actions import ExecuteProcess
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
        ExecuteProcess(
            cmd=[venv_python, '-m', 'remote_control.command_api'],
            cwd=cwd,
            output='screen',
            env=dict(os.environ, DEPTH_BACKEND='fast'),
        ),
    ])
