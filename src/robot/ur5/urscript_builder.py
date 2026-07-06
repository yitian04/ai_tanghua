from __future__ import annotations

import math
from typing import Iterable, List, Sequence

from src.core.models import Trajectory, TrajectoryPoint

PREPARE_JOINT_DEGREES = (45.0, -92.0, 123.0, -32.0, 41.0, 16.68)


def compile_urscript(
    trajectory: Trajectory,
    output_pin: int = 0,
    acceleration: float = 0.05,
    min_speed_m_s: float = 0.005,
    max_speed_m_s: float = 0.5,
    program_name: str = "tanghua_job",
    output_on_delay_s: float = 0.0,
    output_off_delay_s: float = 0.0,
    blend_radius_m: float = 0.001,
    include_prepare_pose: bool = True,
    prepare_joint_degrees: Sequence[float] = PREPARE_JOINT_DEGREES,
    prepare_acceleration: float = 0.12,
    prepare_velocity: float = 0.105,
) -> str:
    points = list(trajectory.points)
    lines = [f"def {program_name}():", f"  set_digital_out({int(output_pin)}, False)"]
    if include_prepare_pose:
        lines.append(f"  movej({_joint_literal(prepare_joint_degrees)}, a={prepare_acceleration:.4f}, v={prepare_velocity:.4f})")
    drawing_state = False

    for idx, point in enumerate(points):
        if point.drawing != drawing_state:
            _append_digital_out(lines, int(output_pin), bool(point.drawing), output_on_delay_s, output_off_delay_s)
            drawing_state = point.drawing
        pose = _pose_literal(point)
        speed = max(min_speed_m_s, min(point.speed_mm_s / 1000.0, max_speed_m_s))
        blend = _blend_radius_for_point(points, idx, blend_radius_m)
        lines.append(f"  movel({pose}, a={acceleration:.4f}, v={speed:.4f}, r={blend:.4f})")

    if drawing_state:
        _append_digital_out(lines, int(output_pin), False, output_on_delay_s, output_off_delay_s)
    if include_prepare_pose:
        lines.append(f"  movej({_joint_literal(prepare_joint_degrees)}, a={prepare_acceleration:.4f}, v={prepare_velocity:.4f})")
    lines.append("end")
    lines.append(f"{program_name}()")
    return "\n".join(lines)


def _append_digital_out(lines: List[str], output_pin: int, enabled: bool, on_delay_s: float, off_delay_s: float) -> None:
    lines.append(f"  set_digital_out({int(output_pin)}, {str(bool(enabled))})")
    delay_s = float(on_delay_s if enabled else off_delay_s)
    if delay_s > 0:
        lines.append(f"  sleep({delay_s:.4f})")


def _blend_radius_for_point(points: List[TrajectoryPoint], idx: int, requested_radius_m: float) -> float:
    requested = max(0.0, float(requested_radius_m))
    if requested <= 0.0 or idx <= 0 or idx >= len(points) - 1:
        return 0.0
    previous = points[idx - 1]
    current = points[idx]
    nxt = points[idx + 1]
    if previous.drawing != current.drawing or nxt.drawing != current.drawing:
        return 0.0
    prev_segment = _point_distance_m(previous, current)
    next_segment = _point_distance_m(current, nxt)
    if prev_segment <= 0.0 or next_segment <= 0.0:
        return 0.0
    return min(requested, 0.4 * prev_segment, 0.4 * next_segment)


def _point_distance_m(a: TrajectoryPoint, b: TrajectoryPoint) -> float:
    dx = (float(a.x_mm) - float(b.x_mm)) / 1000.0
    dy = (float(a.y_mm) - float(b.y_mm)) / 1000.0
    dz = (float(a.z_mm) - float(b.z_mm)) / 1000.0
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _pose_literal(point: TrajectoryPoint) -> str:
    orientation_rad = _orientation_rad([point.rx_deg, point.ry_deg, point.rz_deg])
    values: List[float] = [
        point.x_mm / 1000.0,
        point.y_mm / 1000.0,
        point.z_mm / 1000.0,
        *orientation_rad,
    ]
    return "p[" + ", ".join(f"{value:.6f}" for value in values) + "]"


def _joint_literal(joint_degrees: Sequence[float]) -> str:
    values = list(joint_degrees)
    if len(values) != 6:
        values = list(PREPARE_JOINT_DEGREES)
    return "[" + ", ".join(f"{math.radians(float(value)):.6f}" for value in values) + "]"


def _orientation_rad(orientation_deg: Iterable[float]) -> List[float]:
    values = list(orientation_deg)
    if len(values) != 3:
        values = [0.0, 180.0, 0.0]
    return [math.radians(float(value)) for value in values]
