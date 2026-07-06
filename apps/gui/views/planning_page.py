from __future__ import annotations

from pathlib import Path

import yaml

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st
from matplotlib.collections import LineCollection

from apps.gui.views.file_naming import build_output_path, infer_prefix_from_path, sanitize_filename
from src.core.models import Trajectory
from src.pipeline.export.json_exporter import export_trajectory_json, load_curves_json, load_trajectory_json
from src.pipeline.planning.planner import PlanningConfig, TrajectoryPlanner

DEFAULT_PLANNING_DEFAULTS = {
    "curves_path": "",
    "center_x_mm": 300.0,
    "center_y_mm": 0.0,
    "draw_z_mm": 50.0,
    "tool_rx_deg": 0.0,
    "tool_ry_deg": 180.0,
    "tool_rz_deg": 0.0,
    "workspace_width_mm": 300.0,
    "workspace_height_mm": 300.0,
    "rotation_deg": 0.0,
    "step_mm": 5.0,
    "lift_z_mm": 10.0,
    "use_lift": True,
    "drawing_speed_mm_s": 50.0,
    "travel_speed_mm_s": 150.0,
    "optimize_curve_order": True,
    "exact_order_limit": 10,
    "two_opt_passes": 30,
}


def _planning_defaults(config: dict) -> dict:
    defaults = DEFAULT_PLANNING_DEFAULTS.copy()
    planning = config.get("planning", {}) if isinstance(config, dict) else {}
    if isinstance(planning, dict):
        defaults.update({key: value for key, value in planning.items() if key in defaults})
        # Backward compatibility: older configs stored lift_z_mm as absolute Z.
        # New semantics store lift_z_mm as height above draw_z_mm.
        if "lift_z_mm" in planning and float(defaults.get("lift_z_mm", 0.0)) > float(defaults.get("draw_z_mm", 0.0)):
            defaults["lift_z_mm"] = max(0.0, float(defaults["lift_z_mm"]) - float(defaults["draw_z_mm"]))
    return defaults


def _save_planning_defaults(root_dir: str, values: dict) -> Path:
    config_path = Path(root_dir) / "config" / "settings.yaml"
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        config = {}
    if not isinstance(config, dict):
        config = {}
    config["planning"] = values
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return config_path

def _point_rows(trajectory: Trajectory, limit: int | None = None):
    points = trajectory.points if limit is None else trajectory.points[:limit]
    return [point.to_dict() for point in points]


def _plot_trajectory_xy(trajectory: Trajectory):
    fig, ax = plt.subplots(figsize=(4.4, 3.4), dpi=110)
    drawing_segments = []
    drawing_order = []
    travel_x = []
    travel_y = []
    previous = None

    for point in trajectory.points:
        if point.drawing and previous and previous.drawing and previous.curve_id == point.curve_id:
            drawing_segments.append([(previous.x_mm, previous.y_mm), (point.x_mm, point.y_mm)])
            drawing_order.append(point.point_id)
        if not point.drawing:
            travel_x.append(point.x_mm)
            travel_y.append(point.y_mm)
        previous = point

    if drawing_segments:
        values = np.linspace(0.0, 1.0, len(drawing_segments))
        line_collection = LineCollection(
            drawing_segments,
            cmap="viridis",
            array=values,
            linewidths=1.25,
        )
        ax.add_collection(line_collection)
        colorbar = fig.colorbar(line_collection, ax=ax, fraction=0.045, pad=0.03)
        colorbar.set_label("order", fontsize=7)
        colorbar.set_ticks([0.0, 1.0])
        colorbar.set_ticklabels(["early", "late"])
        colorbar.ax.tick_params(labelsize=7)
    if travel_x:
        ax.scatter(travel_x, travel_y, s=8, color="#888888", alpha=0.75)

    ax.set_aspect("equal", adjustable="box")
    ax.autoscale_view()
    ax.invert_yaxis()
    ax.set_xlabel("robot X / mm")
    ax.set_ylabel("robot Y / mm (down is larger)")
    ax.set_title("XY preview: color order early -> late", fontsize=9)
    ax.grid(True, alpha=0.25)
    fig.tight_layout(pad=0.4)
    return fig


def _plot_trajectory_3d(trajectory: Trajectory):
    fig = plt.figure(figsize=(4.4, 3.4), dpi=110)
    ax = fig.add_subplot(111, projection="3d")
    if trajectory.points:
        xs = [point.x_mm for point in trajectory.points]
        ys = [point.y_mm for point in trajectory.points]
        zs = [point.z_mm for point in trajectory.points]
        colors = ["tab:blue" if point.drawing else "tab:orange" for point in trajectory.points]
        ax.plot(xs, ys, zs, linewidth=0.8, alpha=0.55)
        ax.scatter(xs, ys, zs, c=colors, s=6)
    ax.set_xlabel("X / mm")
    ax.set_ylabel("Y / mm")
    ax.set_zlabel("Z / mm")
    ax.set_title("3D trajectory preview", fontsize=9)
    fig.tight_layout(pad=0.4)
    return fig


def _render_trajectory_summary(trajectory: Trajectory) -> None:
    drawing_points = sum(1 for point in trajectory.points if point.drawing)
    travel_points = len(trajectory.points) - drawing_points

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("ControlPoint 数量", len(trajectory.points))
    col_b.metric("绘制点", drawing_points)
    col_c.metric("空走/抬笔点", travel_points)
    col_d.metric("预计总时间 s", f"{trajectory.metadata.get('estimated_total_time_s', 0.0):.2f}")

    stat_a, stat_b, stat_c, stat_d = st.columns(4)
    stat_a.metric("空走距离 mm", f"{trajectory.metadata.get('ordering_travel_distance_mm', 0.0):.1f}")
    stat_b.metric("绘制长度 mm", f"{trajectory.metadata.get('drawing_length_mm', 0.0):.1f}")
    stat_c.metric("优化器", trajectory.metadata.get("optimizer", "unknown"))
    stat_d.metric("曲线数量", trajectory.metadata.get("curve_count", 0))

    preview_mode = st.radio(
        "预览内容",
        ["XY 预览", "3D 预览", "ControlPointList", "字段说明"],
        horizontal=True,
        label_visibility="collapsed",
    )
    if preview_mode == "XY 预览":
        fig = _plot_trajectory_xy(trajectory)
        st.pyplot(fig, width="content")
        plt.close(fig)
    elif preview_mode == "3D 预览":
        fig = _plot_trajectory_3d(trajectory)
        st.pyplot(fig, width="content")
        plt.close(fig)
    elif preview_mode == "ControlPointList":
        st.caption("中间格式是 Trajectory.points，即按执行顺序排列的 ControlPointList。")
        st.dataframe(_point_rows(trajectory, limit=1000), width="stretch", hide_index=True, height=260)
        if len(trajectory.points) > 1000:
            st.caption(f"仅显示前 1000 行；完整数据在 trajectory.json 中，共 {len(trajectory.points)} 行。")
    else:
        st.json(
            {
                "Trajectory": {
                    "coordinate_frame": trajectory.coordinate_frame,
                    "tool_orientation_deg": trajectory.tool_orientation_deg,
                    "metadata": trajectory.metadata,
                    "points": "list[TrajectoryPoint]",
                },
                "TrajectoryPoint": {
                    "point_id": "执行顺序编号",
                    "curve_id": "来源曲线编号",
                    "x_mm": "机器人基坐标系 X，单位 mm",
                    "y_mm": "机器人基坐标系 Y，单位 mm",
                    "z_mm": "机器人基坐标系 Z，单位 mm",
                    "rx_deg": "TCP 工具姿态 Rx，单位 deg",
                    "ry_deg": "TCP 工具姿态 Ry，单位 deg",
                    "rz_deg": "TCP 工具姿态 Rz，单位 deg",
                    "speed_mm_s": "该点目标速度，单位 mm/s",
                    "drawing": "true 表示出料绘制；false 表示空走/抬笔",
                },
            }
        )


def render(config: dict, root_dir: str) -> None:
    defaults = _planning_defaults(config)
    st.subheader("轨迹规划")
    st.caption("输入 curves.json，输出 robot-independent trajectory.json。")

    generated_this_run = False
    control_col, result_col = st.columns([0.9, 1.6])
    with control_col:
        curves_default = st.session_state.get("latest_curves_path") or defaults["curves_path"]
        curves_path = st.text_input("曲线文件路径", value=curves_default, key="planning_curves_path")

        col_a, col_b, col_c = st.columns(3)
        center_x = col_a.number_input("桌面中心 X mm", value=float(defaults["center_x_mm"]), key="planning_center_x_mm")
        center_y = col_b.number_input("桌面中心 Y mm", value=float(defaults["center_y_mm"]), key="planning_center_y_mm")
        draw_z = col_c.number_input("绘制 Z mm", value=float(defaults["draw_z_mm"]), key="planning_draw_z_mm")

        pose_col_a, pose_col_b, pose_col_c = st.columns(3)
        tool_rx = pose_col_a.number_input("工具姿态 Rx deg", value=float(defaults["tool_rx_deg"]), key="planning_tool_rx_deg")
        tool_ry = pose_col_b.number_input("工具姿态 Ry deg", value=float(defaults["tool_ry_deg"]), key="planning_tool_ry_deg")
        tool_rz = pose_col_c.number_input("工具姿态 Rz deg", value=float(defaults["tool_rz_deg"]), key="planning_tool_rz_deg")
        col_d, col_e, col_f = st.columns(3)
        workspace_w = col_d.number_input("工作区宽 mm", value=float(defaults["workspace_width_mm"]), min_value=1.0, key="planning_workspace_width_mm")
        workspace_h = col_e.number_input("工作区高 mm", value=float(defaults["workspace_height_mm"]), min_value=1.0, key="planning_workspace_height_mm")
        rotation = col_f.number_input("旋转角 deg", value=float(defaults["rotation_deg"]), key="planning_rotation_deg")

        col_g, col_h, col_i = st.columns(3)
        step = col_g.number_input("采样步长 mm", value=float(defaults["step_mm"]), min_value=0.1, key="planning_step_mm")
        lift_z = col_h.number_input("抬笔高度 mm", value=float(defaults["lift_z_mm"]), key="planning_lift_z_mm")
        use_lift = col_i.checkbox("启用抬笔", value=bool(defaults["use_lift"]), key="planning_use_lift")

        col_j, col_k = st.columns(2)
        draw_speed = col_j.number_input("绘制速度 mm/s", value=float(defaults["drawing_speed_mm_s"]), min_value=0.1, key="planning_drawing_speed_mm_s")
        travel_speed = col_k.number_input("空走速度 mm/s", value=float(defaults["travel_speed_mm_s"]), min_value=0.1, key="planning_travel_speed_mm_s")

        optimize_order = st.checkbox("优化曲线顺序以缩短时间", value=bool(defaults["optimize_curve_order"]), key="planning_optimize_curve_order")
        opt_col_a, opt_col_b = st.columns(2)
        exact_limit = opt_col_a.number_input("精确优化上限", value=int(defaults["exact_order_limit"]), min_value=0, max_value=14, step=1, disabled=not optimize_order, key="planning_exact_order_limit")
        two_opt_passes = opt_col_b.number_input("2-opt 轮数", value=int(defaults["two_opt_passes"]), min_value=0, max_value=200, step=5, disabled=not optimize_order, key="planning_two_opt_passes")

        current_defaults = {
            "curves_path": curves_path,
            "center_x_mm": float(center_x),
            "center_y_mm": float(center_y),
            "draw_z_mm": float(draw_z),
            "tool_rx_deg": float(tool_rx),
            "tool_ry_deg": float(tool_ry),
            "tool_rz_deg": float(tool_rz),
            "workspace_width_mm": float(workspace_w),
            "workspace_height_mm": float(workspace_h),
            "rotation_deg": float(rotation),
            "step_mm": float(step),
            "lift_z_mm": float(lift_z),
            "use_lift": bool(use_lift),
            "drawing_speed_mm_s": float(draw_speed),
            "travel_speed_mm_s": float(travel_speed),
            "optimize_curve_order": bool(optimize_order),
            "exact_order_limit": int(exact_limit),
            "two_opt_passes": int(two_opt_passes),
        }
        default_col, generate_col = st.columns([0.9, 1.1])
        set_default_clicked = default_col.button("设为默认值", width="stretch")
        generate_clicked = generate_col.button("生成三维轨迹文件", type="primary", disabled=not curves_path, width="stretch")
        if set_default_clicked:
            saved_path = _save_planning_defaults(root_dir, current_defaults)
            st.success(f"已保存为默认值：{saved_path}")

    with result_col:
        if not curves_path:
            st.info("选择或输入 curves.json 后生成轨迹预览。")

    if generate_clicked:
        source = Path(curves_path)
        if not source.exists():
            st.error("曲线文件不存在")
            return

        planner = TrajectoryPlanner(
            PlanningConfig(
                center_x_mm=center_x,
                center_y_mm=center_y,
                draw_z_mm=draw_z,
                tool_orientation_deg=(float(tool_rx), float(tool_ry), float(tool_rz)),
                workspace_width_mm=workspace_w,
                workspace_height_mm=workspace_h,
                rotation_deg=rotation,
                step_mm=step,
                use_lift=use_lift,
                lift_z_mm=lift_z,
                drawing_speed_mm_s=draw_speed,
                travel_speed_mm_s=travel_speed,
                optimize_curve_order=optimize_order,
                exact_order_limit=int(exact_limit),
                two_opt_passes=int(two_opt_passes),
            )
        )
        trajectory = planner.plan(load_curves_json(source))
        prefix = sanitize_filename(
            st.session_state.get("job_name") or infer_prefix_from_path(str(source), "trajectory"),
            "trajectory",
        )
        st.session_state["job_name"] = prefix
        output = build_output_path(root_dir, "trajectories", prefix, "trajectory", "json")
        export_trajectory_json(trajectory, output)
        st.session_state["latest_trajectory_path"] = str(output)
        with result_col:
            st.success(f"已输出：{output}")
            _render_trajectory_summary(trajectory)
        generated_this_run = True

    latest = st.session_state.get("latest_trajectory_path")
    if latest and Path(latest).exists() and not generated_this_run:
        with result_col:
            st.markdown("#### 最近轨迹文件")
            st.code(latest)
            try:
                _render_trajectory_summary(load_trajectory_json(latest))
            except Exception as exc:
                st.warning(f"轨迹文件预览失败：{exc}")
