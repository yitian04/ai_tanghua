from __future__ import annotations

import re
from pathlib import Path

from src.core.models import Trajectory, TrajectoryPoint
from src.pipeline.export.csv_exporter import load_trajectory_csv
from src.pipeline.export.json_exporter import load_trajectory_json


_WORD_RE = re.compile(r"([XYZF])([-+]?\d+(?:\.\d+)?)", re.IGNORECASE)


def load_trajectory_file(path: str | Path) -> Trajectory:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".json":
        return load_trajectory_json(source)
    if suffix == ".csv":
        return load_trajectory_csv(source)
    if suffix in {".gcode", ".gc", ".nc"}:
        return load_trajectory_gcode(source)
    raise ValueError(f"unsupported trajectory file type: {source.suffix}")


def load_trajectory_gcode(path: str | Path) -> Trajectory:
    points = []
    current = {"X": 0.0, "Y": 0.0, "Z": 0.0, "F": 3000.0}
    drawing = False
    point_id = 0

    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.split(";", 1)[0].strip().upper()
        if not line:
            continue
        if line.startswith("M3"):
            drawing = True
            continue
        if line.startswith("M5"):
            drawing = False
            continue
        if not (line.startswith("G0") or line.startswith("G1")):
            continue
        for key, value in _WORD_RE.findall(line):
            current[key.upper()] = float(value)
        points.append(
            TrajectoryPoint(
                point_id=point_id,
                curve_id=0,
                x_mm=current["X"],
                y_mm=current["Y"],
                z_mm=current["Z"],
                speed_mm_s=current["F"] / 60.0,
                drawing=drawing or line.startswith("G1"),
            )
        )
        point_id += 1

    return Trajectory(points=points, metadata={"source": str(path), "format": "gcode"})
