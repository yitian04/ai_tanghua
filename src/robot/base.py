from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.models import CommandResult, RobotStatus, Trajectory


class RobotAdapter(ABC):
    @abstractmethod
    def connect(self, ip_address: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_status(self) -> RobotStatus:
        raise NotImplementedError

    @abstractmethod
    def check_ready(self) -> CommandResult:
        raise NotImplementedError

    @abstractmethod
    def execute_trajectory(self, trajectory: Trajectory, **options) -> CommandResult:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> CommandResult:
        raise NotImplementedError
