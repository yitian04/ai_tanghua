from __future__ import annotations

import csv
from pathlib import Path

from src.core.models import Trajectory, TrajectoryPoint


FIELDNAMES = ["point_id", "curve_id", "x_mm", "y_mm", "z_mm", "speed_mm_s", "drawing"]


def export_trajectory_csv(trajectory: Trajectory, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        for point in trajectory.points:
            writer.writerow(point.to_dict())
    return output


def load_trajectory_csv(path: str | Path) -> Trajectory:
    points = []
    with Path(path).open("r", newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            points.append(
                TrajectoryPoint(
                    point_id=int(row["point_id"]),
                    curve_id=int(row["curve_id"]),
                    x_mm=float(row["x_mm"]),
                    y_mm=float(row["y_mm"]),
                    z_mm=float(row["z_mm"]),
                    speed_mm_s=float(row["speed_mm_s"]),
                    drawing=str(row["drawing"]).strip().lower() in {"1", "true", "yes", "on"},
                )
            )
    return Trajectory(points=points)
