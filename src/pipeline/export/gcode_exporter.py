from __future__ import annotations

from pathlib import Path

from src.core.models import Trajectory


def export_trajectory_gcode(trajectory: Trajectory, path: str | Path, discharge_on: str = "M3", discharge_off: str = "M5") -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "; Tanghua trajectory",
        "G21 ; units: mm",
        "G90 ; absolute positioning",
    ]
    drawing_state = False
    for point in trajectory.points:
        if point.drawing != drawing_state:
            lines.append(discharge_on if point.drawing else discharge_off)
            drawing_state = point.drawing
        command = "G1" if point.drawing else "G0"
        feed_mm_min = point.speed_mm_s * 60.0
        lines.append(
            f"{command} X{point.x_mm:.3f} Y{point.y_mm:.3f} Z{point.z_mm:.3f} F{feed_mm_min:.1f}"
        )
    if drawing_state:
        lines.append(discharge_off)
    lines.append("M2")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output
