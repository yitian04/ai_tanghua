from __future__ import annotations

import time
from typing import Optional

from src.core.models import CommandResult, RobotStatus, Trajectory
from src.core.validation import validate_trajectory
from src.robot.base import RobotAdapter


class MockRobotAdapter(RobotAdapter):
    def __init__(self, simulate_delay_s: float = 0.0):
        self.ip_address = "mock"
        self.connected = False
        self.simulate_delay_s = simulate_delay_s
        self.last_trajectory: Optional[Trajectory] = None

    def connect(self, ip_address: str = "mock") -> bool:
        self.ip_address = ip_address or "mock"
        self.connected = True
        return True

    def disconnect(self) -> bool:
        self.connected = False
        return True

    def get_status(self) -> RobotStatus:
        return RobotStatus(
            ok=True,
            connected=self.connected,
            robot_mode="MOCK_RUNNING",
            program_state="STOPPED",
            safety_status="NORMAL",
            message="mock robot ready",
        )

    def check_ready(self) -> CommandResult:
        if not self.connected:
            self.connect("mock")
        return CommandResult(ok=True, message="mock robot ready")

    def execute_trajectory(self, trajectory: Trajectory, **_options) -> CommandResult:
        errors = validate_trajectory(trajectory)
        if errors:
            return CommandResult(ok=False, message="; ".join(errors))
        self.last_trajectory = trajectory
        if self.simulate_delay_s > 0:
            time.sleep(self.simulate_delay_s)
        return CommandResult(
            ok=True,
            message=f"mock executed {len(trajectory.points)} trajectory points",
            data={"point_count": len(trajectory.points)},
        )

    def stop(self) -> CommandResult:
        return CommandResult(ok=True, message="mock stopped")
