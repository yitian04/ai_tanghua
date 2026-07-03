from __future__ import annotations

import json
from pathlib import Path

from src.core.models import CurveList, Trajectory


def export_curves_json(curves: CurveList, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(curves.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def load_curves_json(path: str | Path) -> CurveList:
    return CurveList.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def export_trajectory_json(trajectory: Trajectory, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(trajectory.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def load_trajectory_json(path: str | Path) -> Trajectory:
    return Trajectory.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
