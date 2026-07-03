from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ImageResult:
    path: str
    source: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Curve2D:
    points: List[List[float]]
    curve_id: int = 0
    closed: bool = False

    def start(self) -> List[float]:
        return self.points[0] if self.points else [0.0, 0.0]

    def end(self) -> List[float]:
        return self.points[-1] if self.points else [0.0, 0.0]

    def reversed(self) -> "Curve2D":
        return Curve2D(points=list(reversed(self.points)), curve_id=self.curve_id, closed=self.closed)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Curve2D":
        return cls(
            points=[[float(p[0]), float(p[1])] for p in data.get("points", [])],
            curve_id=int(data.get("curve_id", 0)),
            closed=bool(data.get("closed", False)),
        )


@dataclass
class CurveList:
    curves: List[Curve2D] = field(default_factory=list)
    coordinate_frame: str = "image_px"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "coordinate_frame": self.coordinate_frame,
            "metadata": self.metadata,
            "curves": [curve.to_dict() for curve in self.curves],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CurveList":
        return cls(
            curves=[Curve2D.from_dict(item) for item in data.get("curves", [])],
            coordinate_frame=data.get("coordinate_frame", "image_px"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class TrajectoryPoint:
    x_mm: float
    y_mm: float
    z_mm: float
    speed_mm_s: float
    drawing: bool
    curve_id: int = 0
    point_id: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrajectoryPoint":
        return cls(
            x_mm=float(data["x_mm"]),
            y_mm=float(data["y_mm"]),
            z_mm=float(data["z_mm"]),
            speed_mm_s=float(data.get("speed_mm_s", data.get("speed", 50.0))),
            drawing=bool(data.get("drawing", data.get("is_drawing", True))),
            curve_id=int(data.get("curve_id", 0)),
            point_id=int(data.get("point_id", 0)),
        )


@dataclass
class Trajectory:
    points: List[TrajectoryPoint] = field(default_factory=list)
    coordinate_frame: str = "robot_base"
    tool_orientation_deg: List[float] = field(default_factory=lambda: [0.0, 180.0, 0.0])
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "coordinate_frame": self.coordinate_frame,
            "tool_orientation_deg": self.tool_orientation_deg,
            "metadata": self.metadata,
            "points": [point.to_dict() for point in self.points],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Trajectory":
        return cls(
            points=[TrajectoryPoint.from_dict(item) for item in data.get("points", [])],
            coordinate_frame=data.get("coordinate_frame", "robot_base"),
            tool_orientation_deg=[float(v) for v in data.get("tool_orientation_deg", [0.0, 180.0, 0.0])],
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class RobotStatus:
    ok: bool
    message: str = ""
    connected: bool = False
    robot_mode: str = "unknown"
    program_state: str = "unknown"
    safety_status: str = "unknown"
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandResult:
    ok: bool
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

