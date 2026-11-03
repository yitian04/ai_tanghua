"""Local single-line text generation; no image generation or network requests."""
from __future__ import annotations

import json
import math
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from src.core.models import Curve2D, CurveList, Trajectory
from src.pipeline.planning.planner import PlanningConfig, TrajectoryPlanner


@dataclass
class TextLayout:
    height_mm: float = 20.0
    character_gap_mm: float = 2.0
    line_gap_mm: float = 5.0


def generate_text_curves(text: str, root_dir: str | Path, layout: TextLayout | None = None) -> CurveList:
    layout = layout or TextLayout()
    values = asdict(layout)
    if not all(math.isfinite(v) for v in values.values()) or layout.height_mm <= 0 or min(layout.character_gap_mm, layout.line_gap_mm) < 0:
        raise ValueError("字高须大于零，字距和行距须非负，参数必须为有限数值。")
    if not text.strip():
        raise ValueError("请输入文字。")
    if len(text) > 500:
        raise ValueError("第一版每次最多生成 500 个字符。")
    font = None
    directory = Path(root_dir) / "node_modules" / "hanzi-writer-data"
    curves, indexes, missing = [], [], []
    x = y = 0.0
    width = 0.0
    h = layout.height_mm
    for char_index, char in enumerate(text.replace("\r\n", "\n").replace("\r", "\n")):
        if char == "\n":
            width = max(width, x - layout.character_gap_mm)
            x = 0.0
            y += h + layout.line_gap_mm
            continue
        if char == " ":
            x += h * 0.5 + layout.character_gap_mm
            width = max(width, x - layout.character_gap_mm)
            continue
        if 33 <= ord(char) <= 126:
            if font is None:
                try:
                    from HersheyFonts import HersheyFonts
                except ModuleNotFoundError as exc:
                    if exc.name != "HersheyFonts":
                        raise
                    raise ValueError(
                        "当前运行环境缺少英文、数字单线字库 Hershey-Fonts。"
                        "请在 PowerShell 中执行：\n"
                        f'& "{sys.executable}" -m pip install Hershey-Fonts==2.1.0\n'
                        "安装后重新生成即可。纯中文不需要这个依赖。"
                    ) from exc
                font = HersheyFonts()
                font.load_default_font("futural")
                font.normalize_rendering(1.0)
            # normalize_rendering is Y-up: cap y=1, baseline y=.25.
            # Place baseline at .875 of the same em cell used for Hanzi.
            strokes = [[[float(px) * h, (1.125 - float(py)) * h] for px, py in stroke]
                       for stroke in font.strokes_for_text(char)]
            advance = max([0.5 * h] + [px for stroke in strokes for px, _ in stroke]) + h * 0.08
        elif (directory / f"{char}.json").is_file() and ("\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff"):
            data = json.loads((directory / f"{char}.json").read_text(encoding="utf-8"))
            strokes = [[[px / 1024 * h, (900 - py) / 1024 * h] for px, py in stroke] for stroke in data["medians"]]
            advance = h
        else:
            missing.append(char)
            continue
        for stroke_index, stroke in enumerate(strokes):
            if not stroke:
                continue
            curve_id = len(curves)
            curves.append(Curve2D(points=[[px + x, py + y] for px, py in stroke], curve_id=curve_id))
            indexes.append({"curve_id": curve_id, "character": char, "character_index": char_index, "stroke_index": stroke_index})
        x += advance + layout.character_gap_mm
        width = max(width, x - layout.character_gap_mm)
    if missing:
        hint = "；请先运行 npm install 安装汉字字库" if not directory.exists() else ""
        raise ValueError("不支持或缺失的字符：" + "、".join(dict.fromkeys(missing)) + hint)
    if not curves:
        raise ValueError("没有可绘制的笔画。")
    return CurveList(curves=curves, coordinate_frame="layout_mm", metadata={
        "generator": "text_trajectory_v1", "text": text, "layout": values,
        "strokes": indexes, "hanzi_data_version": "2.0.1", "ascii_font": "futural",
        "layout_width_mm": width, "layout_height_mm": y + h,
    })


def generate_text_trajectory(curves: CurveList, config: PlanningConfig) -> Trajectory:
    config = replace(config, coordinate_mode="preserve_mm", optimize_curve_order=False, use_lift=True,
                     center_x_mm=config.center_x_mm - curves.metadata["layout_width_mm"] / 2,
                     center_y_mm=config.center_y_mm - curves.metadata["layout_height_mm"] / 2)
    trajectory = TrajectoryPlanner(config).plan(curves)
    trajectory.metadata.update(curves.metadata)
    return trajectory
