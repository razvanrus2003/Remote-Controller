from setuptools import find_packages, setup

package_name = 'remote_control'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    install_requires=['setuptools', 'pygame'],
    zip_safe=True,
    maintainer='Robot Developer',
    maintainer_email='you@example.com',
    description='ROS2 package for remote controller laptop',
    license='Apache-2.0',
    tests_require=['pytest'],
    data_files=[
        ('share/ament_index/resource_index/packages', [f'resource/{package_name}']),
        (f'share/{package_name}', ['package.xml']),
    ],
    entry_points={
        'console_scripts': [
            'keyboard_publisher = remote_control.keyboard_publisher:main'
        ],
    },
)
