from __future__ import annotations

from typing import Dict, List, Tuple

from src.core.models import Curve2D, CurveList, TrajectoryPoint
from src.pipeline.planning.planner import PlanningConfig, TrajectoryPlanner


ControlPoint = TrajectoryPoint


class CurveProcessor:
    """Compatibility facade over the robot-independent trajectory planner."""

    def __init__(self):
        self.curves: List[Curve2D] = []
        self.optimized_curves: List[Curve2D] = []
        self.all_points: List[TrajectoryPoint] = []
        self.config = PlanningConfig()
        self.last_result: Dict = {}

    def set_desktop_center(self, x: float, y: float, z: float) -> None:
        self.config.center_x_mm = float(x)
        self.config.center_y_mm = float(y)
        self.config.draw_z_mm = float(z)

    def set_workspace_side_length(self, length: float) -> None:
        self.config.workspace_width_mm = float(length)
        self.config.workspace_height_mm = float(length)

    def set_workspace_size(self, width: float, height: float) -> None:
        self.config.workspace_width_mm = float(width)
        self.config.workspace_height_mm = float(height)

    def set_rotation_angle(self, angle_deg: float) -> None:
        self.config.rotation_deg = float(angle_deg)

    def set_step_size(self, step: float) -> None:
        self.config.step_mm = float(step)

    def set_lift_params(self, use_lift: bool, height: float) -> None:
        self.config.use_lift = bool(use_lift)
        self.config.lift_z_mm = float(height)

    def set_speeds(self, drawing_speed: float, travel_speed: float) -> None:
        self.config.drawing_speed_mm_s = float(drawing_speed)
        self.config.travel_speed_mm_s = float(travel_speed)

    def add_curve(self, points: List[Tuple[float, float]]) -> None:
        curve_id = len(self.curves)
        self.curves.append(Curve2D(points=[[float(x), float(y)] for x, y in points], curve_id=curve_id))

    def load_default_shape(self) -> None:
        self.curves = [
            Curve2D(points=[[0, 0], [50, 0], [50, 50], [0, 50], [0, 0]], curve_id=0, closed=True),
            Curve2D(points=[[15, 20], [25, 30], [35, 20]], curve_id=1),
        ]

    def process(self) -> Dict:
        planner = TrajectoryPlanner(self.config)
        trajectory = planner.plan(CurveList(curves=self.curves))
        self.all_points = trajectory.points
        self.optimized_curves = self.curves
        self.last_result = {
            "optimized_curves": self.optimized_curves,
            "total_travel_distance": trajectory.metadata.get("ordering_travel_distance_mm", 0.0),
            "control_points": [point.to_dict() for point in self.all_points],
            "trajectory": trajectory,
            "num_points": len(self.all_points),
            "num_curves": len(self.optimized_curves),
        }
        return self.last_result

    def get_control_points(self) -> List[TrajectoryPoint]:
        return self.all_points

    def get_curve_count(self) -> int:
        return len(self.optimized_curves)

    def get_point_count(self) -> int:
        return len(self.all_points)

    def get_bounding_box(self) -> Dict[str, float]:
        points = self.all_points
        if not points:
            return {"min_x": 0, "max_x": 0, "min_y": 0, "max_y": 0, "min_z": 0, "max_z": 0}
        return {
            "min_x": min(p.x_mm for p in points),
            "max_x": max(p.x_mm for p in points),
            "min_y": min(p.y_mm for p in points),
            "max_y": max(p.y_mm for p in points),
            "min_z": min(p.z_mm for p in points),
            "max_z": max(p.z_mm for p in points),
        }
