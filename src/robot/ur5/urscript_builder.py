from __future__ import annotations

import math
from typing import Iterable, List

from src.core.models import Trajectory, TrajectoryPoint


def compile_urscript(
    trajectory: Trajectory,
    output_pin: int = 0,
    acceleration: float = 0.05,
    min_speed_m_s: float = 0.005,
    max_speed_m_s: float = 0.25,
    program_name: str = "tanghua_job",
) -> str:
    orientation = _orientation_rad(trajectory.tool_orientation_deg)
    lines = [f"def {program_name}():", f"  set_digital_out({int(output_pin)}, False)"]
    drawing_state = False

    for point in trajectory.points:
        if point.drawing != drawing_state:
            lines.append(f"  set_digital_out({int(output_pin)}, {str(bool(point.drawing))})")
            drawing_state = point.drawing
        pose = _pose_literal(point, orientation)
        speed = max(min_speed_m_s, min(point.speed_mm_s / 1000.0, max_speed_m_s))
        lines.append(f"  movel({pose}, a={acceleration:.4f}, v={speed:.4f})")

    if drawing_state:
        lines.append(f"  set_digital_out({int(output_pin)}, False)")
    lines.append("end")
    lines.append(f"{program_name}()")
    return "\n".join(lines)


def _pose_literal(point: TrajectoryPoint, orientation_rad: Iterable[float]) -> str:
    values: List[float] = [
        point.x_mm / 1000.0,
        point.y_mm / 1000.0,
        point.z_mm / 1000.0,
        *orientation_rad,
    ]
    return "p[" + ", ".join(f"{value:.6f}" for value in values) + "]"


def _orientation_rad(orientation_deg: Iterable[float]) -> List[float]:
    values = list(orientation_deg)
    if len(values) != 3:
        values = [0.0, 180.0, 0.0]
    return [math.radians(float(value)) for value in values]
