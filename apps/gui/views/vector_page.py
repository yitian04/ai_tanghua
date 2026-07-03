from __future__ import annotations

import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st
from PIL import Image

from apps.gui.views.file_naming import build_output_path, infer_prefix_from_path, sanitize_filename
from src.core.models import Curve2D, CurveList
from src.modules.image_process_module import image_to_curves
from src.pipeline.export.json_exporter import export_curves_json, load_curves_json


def _plot_curves(
    curve_list: CurveList,
    image_path: str | None = None,
    show_source_image: bool = True,
    source_alpha: float = 0.35,
):
    fig, ax = plt.subplots(figsize=(4.2, 3.4), dpi=110)
    if show_source_image and image_path and Path(image_path).exists():
        image = Image.open(image_path).convert("RGB")
        ax.imshow(image, alpha=float(source_alpha))
        ax.set_xlim(0, image.width)
        ax.set_ylim(image.height, 0)
    for curve in curve_list.curves:
        if len(curve.points) < 2:
            continue
        xs = [point[0] for point in curve.points]
        ys = [point[1] for point in curve.points]
        ax.plot(xs, ys, linewidth=1.0)
        ax.scatter(xs[0], ys[0], s=8, marker="o")
    ax.set_aspect("equal", adjustable="box")
    ax.set_title("CurveList preview", fontsize=9)
    ax.set_xlabel("image x / px")
    ax.set_ylabel("image y / px")
    ax.grid(True, alpha=0.25)
    fig.tight_layout(pad=0.4)
    return fig


def _render_curve_summary(
    curve_list: CurveList,
    image_path: str | None = None,
    show_source_image: bool = True,
    source_alpha: float = 0.35,
) -> None:
    total_points = sum(len(curve.points) for curve in curve_list.curves)
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("曲线数量", len(curve_list.curves))
    col_b.metric("控制点数量", total_points)
    col_c.metric("坐标系", curve_list.coordinate_frame)
    rows = [
        {
            "curve_id": curve.curve_id,
            "point_count": len(curve.points),
            "start": curve.start(),
            "end": curve.end(),
            "closed": curve.closed,
        }
        for curve in curve_list.curves
    ]
    preview_col, table_col = st.columns([1.25, 1])
    with preview_col:
        fig = _plot_curves(
            curve_list,
            image_path=image_path,
            show_source_image=show_source_image,
            source_alpha=source_alpha,
        )
        st.pyplot(fig, use_container_width=False)
        plt.close(fig)
    with table_col:
        st.dataframe(rows, use_container_width=True, hide_index=True, height=230)


def render(config: dict, root_dir: str) -> None:
    del config
    st.subheader("图像转曲线")
    st.caption("输入图片，输出 curves.json；本页不连接机器人。")

    generated_this_run = False
    control_col, result_col = st.columns([0.85, 1.65])
    with control_col:
        image_path = st.text_input("图片路径", value=st.session_state.get("latest_image_path", ""))
        show_source_image = st.checkbox("预览叠加原图", value=True)
        source_alpha = st.slider("原图透明度", 0.0, 1.0, 0.35, 0.05, disabled=not show_source_image)
        threshold = st.slider("二值化阈值", 0, 255, 128)
        min_area = st.number_input("最小轮廓面积", min_value=1, max_value=100000, value=50, step=10)
        epsilon = st.number_input("轮廓简化精度", min_value=0.1, max_value=50.0, value=2.0, step=0.5)
        generate_clicked = st.button("生成曲线文件", type="primary", disabled=not image_path, use_container_width=True)

    with result_col:
        if not image_path:
            st.info("选择或输入图片路径后生成曲线预览。")

    if generate_clicked:
        source = Path(image_path)
        if not source.exists():
            st.error("图片路径不存在")
            return
        image = Image.open(source).convert("RGB")
        curves_raw = image_to_curves(np.array(image), binary_threshold=threshold, min_contour_area=int(min_area), approximate_epsilon=float(epsilon))
        if not curves_raw:
            st.error("未提取到有效曲线，请调整阈值或图片。")
            return

        curve_list = CurveList(
            curves=[Curve2D(points=[[float(x), float(y)] for x, y in curve], curve_id=idx) for idx, curve in enumerate(curves_raw)],
            coordinate_frame="image_px",
            metadata={"source_image": str(source), "threshold": threshold, "min_area": int(min_area), "epsilon": float(epsilon)},
        )
        prefix = sanitize_filename(st.session_state.get("job_name") or infer_prefix_from_path(str(source), "image"), "image")
        st.session_state["job_name"] = prefix
        output = build_output_path(root_dir, "curves", prefix, "curves", "json")
        export_curves_json(curve_list, output)
        st.session_state["latest_curves_path"] = str(output)
        with result_col:
            st.success(f"已输出：{output}")
            _render_curve_summary(
                curve_list,
                image_path=str(source),
                show_source_image=show_source_image,
                source_alpha=source_alpha,
            )
        generated_this_run = True

    latest = st.session_state.get("latest_curves_path")
    if latest and Path(latest).exists() and not generated_this_run:
        with result_col:
            st.markdown("#### 最近曲线文件")
            st.code(latest)
            try:
                curve_list = load_curves_json(latest)
                image_for_preview = curve_list.metadata.get("source_image") or st.session_state.get("latest_image_path", "")
                _render_curve_summary(
                    curve_list,
                    image_path=image_for_preview,
                    show_source_image=show_source_image,
                    source_alpha=source_alpha,
                )
            except Exception as exc:
                st.warning(f"曲线文件预览失败：{exc}")
