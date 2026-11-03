from __future__ import annotations

from typing import List
import math

from .models import Trajectory


def validate_trajectory(trajectory: Trajectory) -> List[str]:
    errors: List[str] = []
    if not trajectory.points:
        return ["trajectory has no points"]

    if trajectory.coordinate_frame != "robot_base": errors.append("trajectory must use robot_base coordinates")
    for idx, point in enumerate(trajectory.points):
        if not isinstance(point.speed_mm_s,(int,float)) or not math.isfinite(point.speed_mm_s) or point.speed_mm_s <= 0:
            errors.append(f"point {idx} speed must be positive")
        if not all(isinstance(value, (int, float)) and not isinstance(value,bool) and math.isfinite(value) for value in (point.x_mm, point.y_mm, point.z_mm)):
            errors.append(f"point {idx} contains non-numeric coordinates")
        if not all(isinstance(value, (int, float)) and not isinstance(value,bool) and math.isfinite(value) for value in (point.rx_deg, point.ry_deg, point.rz_deg)):
            errors.append(f"point {idx} contains non-numeric tool orientation")
    return errors
