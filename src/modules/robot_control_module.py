from __future__ import annotations

from typing import Dict, List

from src.core.models import Trajectory
from src.robot.ur5.ur5_adapter import UR5RobotAdapter


def execute_path(
    points: List[Dict],
    robot_ip: str = "192.168.1.100",
    output_pin: int = 0,
    connect: bool = True,
    **compile_options,
) -> bool:
    controller = UR5RobotAdapter()
    try:
        if connect and not controller.connect(robot_ip):
            return False
        return controller.execute_path(points, output_pin=output_pin, **compile_options)
    finally:
        controller.disconnect()


def execute_trajectory(
    trajectory: Trajectory,
    robot_ip: str = "192.168.1.100",
    output_pin: int = 0,
    **compile_options,
) -> bool:
    controller = UR5RobotAdapter()
    try:
        if not controller.connect(robot_ip):
            return False
        return controller.execute_trajectory(trajectory, output_pin=output_pin, **compile_options).ok
    finally:
        controller.disconnect()


def compile_urscript(points: List[Dict], output_pin: int = 0, **compile_options) -> str:
    controller = UR5RobotAdapter()
    return controller.compile_urscript(points, output_pin=output_pin, **compile_options)


def set_discharge(robot_ip: str, enabled: bool, output_pin: int = 0) -> bool:
    controller = UR5RobotAdapter()
    try:
        if not controller.connect(robot_ip):
            return False
        return controller.set_discharge(enabled, output_pin=output_pin)
    finally:
        controller.disconnect()


def stop_program(robot_ip: str) -> bool:
    controller = UR5RobotAdapter()
    try:
        if not controller.connect(robot_ip):
            return False
        return controller.stop_program()
    finally:
        controller.disconnect()
