from __future__ import annotations

from pathlib import Path
from typing import Callable

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st
from matplotlib.collections import LineCollection
from PIL import Image

from apps.gui.views.file_naming import build_output_path, infer_prefix_from_path, sanitize_filename
from apps.gui.views.planning_page import _planning_defaults
from apps.gui.views.ur_execution_controls import execution_profile_caption
from src.core.models import CurveList, Trajectory
from src.modules.image_process_module import create_binary_preview, vectorize_image_to_curve_list
from src.pipeline.export.json_exporter import export_curves_json, export_trajectory_json
from src.pipeline.planning.planner import PlanningConfig, TrajectoryPlanner
from src.pipeline.vectorization import VectorizationToolError
from src.robot.ur5 import UR5RobotAdapter
from src.robot.ur5.execution_profile import execution_profile_from_config


VECTOR_DEFAULTS = {
    "threshold_method": "otsu",
    "binary_threshold": 128,
    "blur_size": 3,
    "adaptive_block_size": 31,
    "adaptive_c": 5,
    "min_component_area": 20,
    "bridge_gap_px": 2,
    "stroke_max_width_px": 18.0,
    "sample_tolerance": 1.2,
    "area_epsilon": 2.0,
    "min_path_length": 8,
    "smooth_iterations": 0,
    "min_curve_length_ratio": 0.01,
    "max_vectorize_dim": 1024,
    "vectorizer": "mixed_stroke_svg",
    "outline_engine": "auto",
}


def _get_ur5(config: dict) -> UR5RobotAdapter:
    robot_config = config.get("robot", {}) if isinstance(config, dict) else {}
    if "ur5_robot" not in st.session_state or not hasattr(st.session_state.ur5_robot, "execute_trajectory"):
        st.session_state.ur5_robot = UR5RobotAdapter(
            dashboard_port=int(robot_config.get("dashboard_port", 29999)),
            script_port=int(robot_config.get("script_port", 30002)),
            timeout=float(robot_config.get("timeout", 5)),
        )
    return st.session_state.ur5_robot


def _save_uploaded_or_path(root_dir: str, uploaded, image_path: str, job_name: str) -> Path:
    if uploaded is not None:
        suffix = Path(uploaded.name).suffix.lower() or ".png"
        prefix = sanitize_filename(job_name or Path(uploaded.name).stem, fallback="input")
        output = build_output_path(root_dir, "images", prefix, "input", suffix)
        output.write_bytes(uploaded.getbuffer())
        st.session_state["job_name"] = prefix
        st.session_state["latest_image_path"] = str(output)
        return output

    source = Path(image_path)
    if not source.is_file():
        raise FileNotFoundError(f"图片路径不存在或不是文件：{source}")
    prefix = sanitize_filename(job_name or infer_prefix_from_path(str(source), "input"), fallback="input")
    st.session_state["job_name"] = prefix
    st.session_state["latest_image_path"] = str(source)
    return source


def _plot_curves(curve_list: CurveList, image_size: tuple[int, int] | None = None):
    fig, ax = plt.subplots(figsize=(4.6, 3.6), dpi=110)
    segments = []
    for curve in curve_list.curves:
        if len(curve.points) < 2:
            continue
        segments.extend([(curve.points[idx - 1], curve.points[idx]) for idx in range(1, len(curve.points))])

    if segments:
        values = np.linspace(0.0, 1.0, len(segments))
        collection = LineCollection(segments, cmap="viridis", array=values, linewidths=1.1)
        ax.add_collection(collection)
        colorbar = fig.colorbar(collection, ax=ax, fraction=0.045, pad=0.03)
        colorbar.set_label("order", fontsize=7)
        colorbar.set_ticks([0.0, 1.0])
        colorbar.set_ticklabels(["early", "late"])
        colorbar.ax.tick_params(labelsize=7)

    if image_size:
        width, height = image_size
        ax.set_xlim(0, width)
        ax.set_ylim(height, 0)
    else:
        ax.autoscale_view()
        ax.invert_yaxis()
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("image X / px")
    ax.set_ylabel("image Y / px, upward decreases")
    ax.set_title("Curve preview: color order early -> late", fontsize=9)
    ax.grid(True, alpha=0.25)
    fig.tight_layout(pad=0.4)
    return fig


def _plot_trajectory_xy(trajectory: Trajectory):
    fig, ax = plt.subplots(figsize=(4.6, 3.6), dpi=110)
    segments = []
    previous = None
    for point in trajectory.points:
        if previous and point.drawing and previous.drawing and point.curve_id == previous.curve_id:
            segments.append([(previous.x_mm, previous.y_mm), (point.x_mm, point.y_mm)])
        previous = point

    if segments:
        values = np.linspace(0.0, 1.0, len(segments))
        collection = LineCollection(segments, cmap="viridis", array=values, linewidths=1.1)
        ax.add_collection(collection)
        colorbar = fig.colorbar(collection, ax=ax, fraction=0.045, pad=0.03)
        colorbar.set_label("order", fontsize=7)
        colorbar.set_ticks([0.0, 1.0])
        colorbar.set_ticklabels(["early", "late"])
        colorbar.ax.tick_params(labelsize=7)
    ax.set_aspect("equal", adjustable="box")
    ax.autoscale_view()
    ax.invert_yaxis()
    ax.set_xlabel("robot X / mm")
    ax.set_ylabel("robot Y / mm, upward decreases")
    ax.set_title("Trajectory XY preview", fontsize=9)
    ax.grid(True, alpha=0.25)
    fig.tight_layout(pad=0.4)
    return fig


def _plan_trajectory(config: dict, curve_list: CurveList) -> Trajectory:
    defaults = _planning_defaults(config)
    planner = TrajectoryPlanner(
        PlanningConfig(
            center_x_mm=float(defaults["center_x_mm"]),
            center_y_mm=float(defaults["center_y_mm"]),
            draw_z_mm=float(defaults["draw_z_mm"]),
            tool_orientation_deg=(
                float(defaults["tool_rx_deg"]),
                float(defaults["tool_ry_deg"]),
                float(defaults["tool_rz_deg"]),
            ),
            workspace_width_mm=float(defaults["workspace_width_mm"]),
            workspace_height_mm=float(defaults["workspace_height_mm"]),
            rotation_deg=float(defaults["rotation_deg"]),
            step_mm=float(defaults["step_mm"]),
            use_lift=bool(defaults["use_lift"]),
            lift_z_mm=float(defaults["lift_z_mm"]),
            drawing_speed_mm_s=float(defaults["drawing_speed_mm_s"]),
            travel_speed_mm_s=float(defaults["travel_speed_mm_s"]),
            optimize_curve_order=bool(defaults["optimize_curve_order"]),
            exact_order_limit=int(defaults["exact_order_limit"]),
            two_opt_passes=int(defaults["two_opt_passes"]),
        )
    )
    return planner.plan(curve_list)


def _run_pipeline(
    config: dict,
    root_dir: str,
    source: Path,
    execute_robot: bool,
    robot_ip: str,
    update_step: Callable[[str, str], None],
) -> tuple[CurveList, Trajectory, Path, Path, dict]:
    image = Image.open(source).convert("RGB")
    image_array = np.array(image)
    prefix = sanitize_filename(st.session_state.get("job_name") or infer_prefix_from_path(str(source), "job"), "job")

    update_step("二值化", "运行中")
    binary_preview, binary_analysis = create_binary_preview(
        image_array,
        threshold_method=VECTOR_DEFAULTS["threshold_method"],
        binary_threshold=int(VECTOR_DEFAULTS["binary_threshold"]),
        blur_size=int(VECTOR_DEFAULTS["blur_size"]),
        adaptive_block_size=int(VECTOR_DEFAULTS["adaptive_block_size"]),
        adaptive_c=int(VECTOR_DEFAULTS["adaptive_c"]),
        min_component_area=int(VECTOR_DEFAULTS["min_component_area"]),
        bridge_gap_px=int(VECTOR_DEFAULTS["bridge_gap_px"]),
        max_preview_dim=int(VECTOR_DEFAULTS["max_vectorize_dim"]),
        input_mode="auto",
        stroke_max_width_px=float(VECTOR_DEFAULTS["stroke_max_width_px"]),
    )
    update_step("二值化", "完成")

    update_step("图像转曲线", "运行中")
    curves_path = build_output_path(root_dir, "curves", prefix, "curves", "json")
    svg_output = build_output_path(root_dir, "curves", prefix, "strokes", "svg")
    curve_list = vectorize_image_to_curve_list(
        image_array,
        threshold_method=VECTOR_DEFAULTS["threshold_method"],
        binary_threshold=int(VECTOR_DEFAULTS["binary_threshold"]),
        blur_size=int(VECTOR_DEFAULTS["blur_size"]),
        adaptive_block_size=int(VECTOR_DEFAULTS["adaptive_block_size"]),
        adaptive_c=int(VECTOR_DEFAULTS["adaptive_c"]),
        min_component_area=int(VECTOR_DEFAULTS["min_component_area"]),
        bridge_gap_px=int(VECTOR_DEFAULTS["bridge_gap_px"]),
        min_curve_length_ratio=float(VECTOR_DEFAULTS["min_curve_length_ratio"]),
        line_simplify_epsilon=float(VECTOR_DEFAULTS["sample_tolerance"]),
        area_simplify_epsilon=float(VECTOR_DEFAULTS["area_epsilon"]),
        min_path_length=int(VECTOR_DEFAULTS["min_path_length"]),
        smooth_iterations=int(VECTOR_DEFAULTS["smooth_iterations"]),
        max_vectorize_dim=int(VECTOR_DEFAULTS["max_vectorize_dim"]),
        stroke_max_width_px=float(VECTOR_DEFAULTS["stroke_max_width_px"]),
        source_image=str(source),
        vectorizer=str(VECTOR_DEFAULTS["vectorizer"]),
        outline_engine=str(VECTOR_DEFAULTS["outline_engine"]),
        svg_output_path=svg_output,
        work_dir=Path(root_dir) / "data" / "vectorization_temp",
    )
    if not curve_list.curves:
        raise RuntimeError("图像转曲线完成，但没有生成有效曲线。")
    export_curves_json(curve_list, curves_path)
    st.session_state["latest_curves_path"] = str(curves_path)
    update_step("图像转曲线", "完成")

    update_step("轨迹规划", "运行中")
    trajectory = _plan_trajectory(config, curve_list)
    if not trajectory.points:
        raise RuntimeError("轨迹规划完成，但没有生成轨迹点。")
    trajectory_path = build_output_path(root_dir, "trajectories", prefix, "trajectory", "json")
    export_trajectory_json(trajectory, trajectory_path)
    st.session_state["latest_trajectory_path"] = str(trajectory_path)
    update_step("轨迹规划", "完成")

    if execute_robot:
        update_step("机械臂执行", "运行中")
        robot = _get_ur5(config)
        robot.set_ip(robot_ip)
        profile = execution_profile_from_config(config)
        st.session_state.motion_in_progress = True
        try:
            result = robot.execute_trajectory(
                trajectory,
                output_pin=profile.output_pin,
                **profile.compile_options(),
            )
        finally:
            st.session_state.motion_in_progress = False
        if not result.ok:
            raise RuntimeError(result.message)
        update_step("机械臂执行", "完成")

    return curve_list, trajectory, curves_path, trajectory_path, {"preview": binary_preview, "analysis": binary_analysis, "image_size": image.size}


def render(config: dict, root_dir: str) -> None:
    st.subheader("一键绘制")
    st.caption("按默认参数串联：输入图像 -> 二值化 -> 曲线 -> 三维轨迹 -> UR5 URScript。")

    robot_config = config.get("robot", {}) if isinstance(config, dict) else {}
    default_ip = st.session_state.get("robot_ip", robot_config.get("ip", "192.168.1.100"))

    left, right = st.columns([0.85, 1.65])
    with left:
        job_name = st.text_input("任务名/文件名前缀", value=st.session_state.get("job_name", ""), key="one_click_job_name")
        uploaded = st.file_uploader("上传输入图片", type=["png", "jpg", "jpeg", "bmp"], key="one_click_upload")
        image_path = st.text_input("或输入图片路径", value=st.session_state.get("latest_image_path", ""), key="one_click_image_path")
        robot_ip = st.text_input("UR5 IP", value=str(default_ip), key="one_click_robot_ip")
        execute_robot = st.checkbox("生成后立即发送 URScript 给 UR5", value=False)
        execute_confirmed = st.checkbox("我确认机械臂现场安全，允许自动运动", value=False, disabled=not execute_robot)
        st.caption(execution_profile_caption(execution_profile_from_config(config)))

        preview_clicked = st.button("一键生成预览", width="stretch", disabled=uploaded is None and not image_path)
        execute_clicked = st.button(
            "一键生成并绘制",
            type="primary",
            width="stretch",
            disabled=(uploaded is None and not image_path) or not execute_robot or not execute_confirmed or st.session_state.get("motion_in_progress", False),
        )

    step_slot = right.empty()
    preview_box = right.container()

    if not (preview_clicked or execute_clicked):
        with preview_box:
            st.info("上传或输入图片后，可先生成预览；确认现场安全后再一键绘制。")
        return

    steps: dict[str, str] = {
        "输入图像": "等待",
        "二值化": "等待",
        "图像转曲线": "等待",
        "轨迹规划": "等待",
        "机械臂执行": "跳过" if not execute_clicked else "等待",
    }

    def update_step(name: str, state: str) -> None:
        steps[name] = state
        with step_slot.container():
            st.markdown("#### 流程状态")
            st.dataframe([{"步骤": key, "状态": value} for key, value in steps.items()], width="stretch", hide_index=True, height=190)

    try:
        update_step("输入图像", "运行中")
        source = _save_uploaded_or_path(root_dir, uploaded, image_path, job_name)
        update_step("输入图像", "完成")
        curve_list, trajectory, curves_path, trajectory_path, binary = _run_pipeline(
            config=config,
            root_dir=root_dir,
            source=source,
            execute_robot=False,
            robot_ip=robot_ip,
            update_step=update_step,
        )
    except VectorizationToolError as exc:
        update_step("图像转曲线", "失败")
        st.error(f"图像转曲线失败：{exc}")
        return
    except Exception as exc:
        failed_step = next((key for key, value in steps.items() if value == "运行中"), "流水线")
        update_step(failed_step, "失败")
        st.error(f"{failed_step}失败：{exc}")
        return

    with preview_box:
        st.success("轨迹生成完成")
        st.code(str(curves_path))
        st.code(str(trajectory_path))
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("曲线数", len(curve_list.curves))
        col_b.metric("轨迹点", len(trajectory.points))
        col_c.metric("预计时间 s", f"{trajectory.metadata.get('estimated_total_time_s', 0.0):.2f}")

        tab_binary, tab_curves, tab_trajectory = st.tabs(["二值化", "曲线预览", "轨迹预览"])
        with tab_binary:
            st.image(Image.fromarray(binary["preview"]), width="stretch")
            st.caption(
                f"components={binary['analysis'].get('component_count')}; "
                f"line={binary['analysis'].get('line_component_count')}; "
                f"area={binary['analysis'].get('area_component_count')}"
            )
        with tab_curves:
            fig = _plot_curves(curve_list, image_size=binary.get("image_size"))
            st.pyplot(fig, width="content")
            plt.close(fig)
        with tab_trajectory:
            fig = _plot_trajectory_xy(trajectory)
            st.pyplot(fig, width="content")
            plt.close(fig)
    if execute_clicked:
        try:
            update_step("机械臂执行", "运行中")
            robot = _get_ur5(config)
            robot.set_ip(robot_ip)
            profile = execution_profile_from_config(config)
            st.session_state.motion_in_progress = True
            try:
                result = robot.execute_trajectory(
                    trajectory,
                    output_pin=profile.output_pin,
                    **profile.compile_options(),
                )
            finally:
                st.session_state.motion_in_progress = False
            if not result.ok:
                update_step("机械臂执行", "失败")
                st.error(f"机械臂执行失败：{result.message}")
                return
            update_step("机械臂执行", "完成")
            st.success(result.message)
        except Exception as exc:
            update_step("机械臂执行", "失败")
            st.error(f"机械臂执行失败：{exc}")
