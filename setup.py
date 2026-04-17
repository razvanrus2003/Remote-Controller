from setuptools import setup

package_name = 'remote_control'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Robot Developer',
    maintainer_email='you@example.com',
    description='ROS2 package for remote controller laptop',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'keyboard_publisher = remote_control.keyboard_publisher:main',
            'video_subscriber = remote_control.video_subscriber:main',
        ],
    },
)
