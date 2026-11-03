from __future__ import annotations

from apps.gui.parameter_ui import ui as st

from apps.gui.views.planning_page import _planning_defaults
from src.pipeline.planning.planner import PlanningConfig


def planning_controls(config: dict, prefix: str) -> PlanningConfig:
    defaults = _planning_defaults(config)
    def number(label, name, default, minimum=None):
        return st.number_input(label, value=float(defaults.get(name, default)), min_value=minimum, key=f"{prefix}_{name}")
    a, b = st.columns(2)
    with a:
        x = number("中心 X mm", "center_x_mm", 300)
        z = number("绘制 Z mm", "draw_z_mm", 50)
        speed = number("绘制速度 mm/s", "drawing_speed_mm_s", 50, 0.1)
    with b:
        y = number("中心 Y mm", "center_y_mm", 0)
        lift = number("抬笔高度 mm", "lift_z_mm", 10, 0.1)
        travel = number("空走速度 mm/s", "travel_speed_mm_s", 150, 0.1)
    step = number("采样间距 mm", "step_mm", 1, 0.1)
    with st.expander("工具姿态"):
        rx = number("Rx deg", "tool_rx_deg", 0)
        ry = number("Ry deg", "tool_ry_deg", 180)
        rz = number("Rz deg", "tool_rz_deg", 0)
    return PlanningConfig(center_x_mm=x, center_y_mm=y, draw_z_mm=z, lift_z_mm=lift,
                          drawing_speed_mm_s=speed, travel_speed_mm_s=travel, step_mm=step,
                          tool_orientation_deg=(rx, ry, rz))
