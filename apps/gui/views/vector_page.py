from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st
from PIL import Image

from apps.gui.views.file_naming import build_output_path, infer_prefix_from_path, sanitize_filename
from src.core.models import CurveList
from src.modules.image_process_module import create_binary_preview, vectorize_image_to_curve_list
from src.pipeline.export.json_exporter import export_curves_json, load_curves_json
from src.pipeline.vectorization import VectorizationToolError, available_vectorization_tools


METHOD_LABELS = {
    "Auto mixed strokes/areas": "mixed_stroke_svg",
    "Line-only skeleton SVG": "skeleton_stroke_svg",
    "Area-only outline SVG": "outline_svg",
    "OpenCV fallback": "opencv_fallback",
}

THRESHOLD_LABELS = {
    "Otsu auto": "otsu",
    "Adaptive": "adaptive",
    "Manual": "manual",
}


def _plot_curves(
    curve_list: CurveList,
    image_path: str | None = None,
    show_source_image: bool = True,
    source_alpha: float = 0.35,
):
    fig, ax = plt.subplots(figsize=(4.2, 3.4), dpi=110)
    if show_source_image and image_path and Path(image_path).is_file():
        image = Image.open(image_path).convert("RGB")
        ax.imshow(image, alpha=float(source_alpha))
        ax.set_xlim(0, image.width)
        ax.set_ylim(image.height, 0)

    total = max(1, len(curve_list.curves) - 1)
    for idx, curve in enumerate(curve_list.curves):
        if len(curve.points) < 2:
            continue
        xs = [point[0] for point in curve.points]
        ys = [point[1] for point in curve.points]
        color = plt.cm.viridis(idx / total)
        ax.plot(xs, ys, linewidth=1.0, color=color)
        ax.scatter(xs[0], ys[0], s=6, marker="o", color=color)

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
    col_a.metric("Curves", len(curve_list.curves))
    col_b.metric("Points", total_points)
    col_c.metric("Frame", curve_list.coordinate_frame)

    source_svg = curve_list.metadata.get("stroke_svg_output_path") or curve_list.metadata.get("source_svg") or curve_list.metadata.get("svg_output_path")
    if source_svg:
        st.caption(f"SVG: {source_svg}")

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
        st.pyplot(fig, width="content")
        plt.close(fig)
    with table_col:
        st.dataframe(rows, width="stretch", hide_index=True, height=230)


def _render_binary_preview(preview: np.ndarray, analysis: dict) -> None:
    st.markdown("#### Binary preview")
    st.image(Image.fromarray(preview), width="stretch")
    st.caption(
        f"components={analysis['component_count']}; "
        f"stroke-line={analysis['line_component_count']}; "
        f"area={analysis['area_component_count']}; "
        f"p90 width={float(analysis['p90_stroke_width_px']):.1f}px. "
        "black=line skeleton, gray=area outline."
    )
    original_size = analysis.get("original_image_size")
    processing_size = analysis.get("processing_image_size")
    if original_size and processing_size:
        st.caption(f"process size: {original_size[0]}x{original_size[1]} -> {processing_size[0]}x{processing_size[1]}")

    rows = [
        {
            "type": item["content_type"],
            "x": item["x"],
            "y": item["y"],
            "w": item["width"],
            "h": item["height"],
            "area": item["area"],
            "aspect": round(float(item["bbox_aspect"]), 2),
            "fill": round(float(item["fill_ratio"]), 2),
            "p90_width": round(float(item["p90_stroke_width_px"]), 1),
        }
        for item in analysis.get("components", [])
    ]
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True, height=140)


def _preview_mode(vectorizer: str) -> str:
    if vectorizer == "skeleton_stroke_svg":
        return "line_only"
    if vectorizer == "outline_svg":
        return "area_only"
    return "auto"


def _ensure_binary_preview(
    image_path: str,
    signature: tuple,
    threshold_method: str,
    threshold: int,
    blur_size: int,
    adaptive_block_size: int,
    adaptive_c: int,
    min_component_area: int,
    bridge_gap_px: int,
    max_preview_dim: int,
    input_mode: str,
    stroke_max_width_px: float,
) -> bool:
    if not image_path:
        return False
    if st.session_state.get("vector_binary_signature") == signature and st.session_state.get("vector_binary_preview") is not None:
        return True

    source = Path(image_path)
    if not source.is_file():
        return False

    image = Image.open(source).convert("RGB")
    preview, analysis = create_binary_preview(
        np.array(image),
        threshold_method=threshold_method,  # type: ignore[arg-type]
        binary_threshold=threshold,
        blur_size=int(blur_size),
        adaptive_block_size=int(adaptive_block_size),
        adaptive_c=int(adaptive_c),
        min_component_area=int(min_component_area),
        bridge_gap_px=int(bridge_gap_px),
        max_preview_dim=int(max_preview_dim),
        input_mode=input_mode,  # type: ignore[arg-type]
        stroke_max_width_px=float(stroke_max_width_px),
    )
    st.session_state["vector_binary_signature"] = signature
    st.session_state["vector_binary_preview"] = preview
    st.session_state["vector_binary_analysis"] = analysis
    return True


def _method_available(method: str, outline_engine: str, tools: dict[str, str | None]) -> tuple[bool, str]:
    if method in {"opencv_fallback", "skeleton_stroke_svg"}:
        return True, "No external CLI required for line skeleton extraction."
    if method == "mixed_stroke_svg":
        if tools.get("vtracer") or tools.get("potrace"):
            return True, "Line strokes use skeleton; area outlines use VTracer/Potrace."
        return True, "Line strokes work; area outlines will fall back to OpenCV contours."
    if outline_engine == "vtracer":
        return bool(tools.get("vtracer")), f"VTracer: {tools.get('vtracer') or 'not found'}"
    if outline_engine == "potrace":
        return bool(tools.get("potrace")), f"Potrace: {tools.get('potrace') or 'not found'}"
    if tools.get("vtracer"):
        return True, f"auto uses VTracer: {tools['vtracer']}"
    if tools.get("potrace"):
        return True, f"auto uses Potrace: {tools['potrace']}"
    return False, "VTracer/Potrace not found. Put executable under tools/VTracer/ or tools/Potrace/."


def render(config: dict, root_dir: str) -> None:
    del config
    st.subheader("Image to curves")
    st.caption("Input image, output CurveList JSON and optional stroke-only SVG. This page does not connect to the robot.")

    generated_this_run = False
    tools = available_vectorization_tools()
    control_col, result_col = st.columns([0.85, 1.65])

    with control_col:
        image_path = st.text_input("Image path", value=st.session_state.get("latest_image_path", ""))
        show_source_image = st.checkbox("Overlay source image", value=True)
        source_alpha = st.slider("Source alpha", 0.0, 1.0, 0.35, 0.05, disabled=not show_source_image)

        method_label = st.selectbox("Vectorization method", list(METHOD_LABELS.keys()), index=0)
        vectorizer = METHOD_LABELS[method_label]
        input_mode = _preview_mode(vectorizer)
        outline_engine = "auto"
        if vectorizer in {"outline_svg", "mixed_stroke_svg"}:
            outline_engine = st.selectbox("Outline SVG backend", ["auto", "vtracer", "potrace"], index=0)

        available, status_text = _method_available(vectorizer, outline_engine, tools)
        if available:
            st.caption(status_text)
        else:
            st.warning(status_text)

        threshold_label = st.selectbox("Binarization", list(THRESHOLD_LABELS.keys()), index=0)
        threshold_method = THRESHOLD_LABELS[threshold_label]
        threshold = st.slider("Manual threshold", 0, 255, 128, disabled=threshold_method != "manual")
        blur_size = st.selectbox("Blur kernel", [0, 3, 5, 7], index=1)
        adaptive_block_size = st.selectbox("Adaptive window", [15, 21, 31, 45, 61], index=2, disabled=threshold_method != "adaptive")
        adaptive_c = st.slider("Adaptive C", -10, 20, 5, disabled=threshold_method != "adaptive")
        min_component_area = st.number_input("Min component area", min_value=1, max_value=100000, value=20, step=5)
        bridge_gap_px = st.slider("Bridge small gaps px", 0, 6, 2)
        stroke_max_width_px = st.number_input("Max stroke width for skeleton px", min_value=1.0, max_value=200.0, value=18.0, step=1.0, disabled=vectorizer == "outline_svg")
        sample_tolerance = st.number_input("Curve sampling/simplify px", min_value=0.2, max_value=20.0, value=1.2, step=0.2)
        min_curve_ratio_pct = st.number_input("Short curve filter %", min_value=0.0, max_value=10.0, value=1.0, step=0.1)
        max_vectorize_dim = st.number_input("Max processing side", min_value=256, max_value=4096, value=1024, step=128)

        with st.expander("Skeleton fallback parameters", expanded=vectorizer in {"mixed_stroke_svg", "skeleton_stroke_svg"}):
            area_epsilon = st.number_input("Area simplify px", min_value=0.1, max_value=30.0, value=2.0, step=0.5)
            smooth_iterations = st.slider("Line smoothing iterations", 0, 3, 0)
            min_path_length = st.number_input("Min skeleton path length", min_value=2, max_value=1000, value=8, step=1)

        binary_signature = (
            image_path,
            vectorizer,
            input_mode,
            threshold_method,
            int(threshold),
            int(blur_size),
            int(adaptive_block_size),
            int(adaptive_c),
            int(min_component_area),
            int(bridge_gap_px),
            float(stroke_max_width_px),
            int(max_vectorize_dim),
        )
        binary_ready = _ensure_binary_preview(
            image_path=image_path,
            signature=binary_signature,
            threshold_method=threshold_method,
            threshold=int(threshold),
            blur_size=int(blur_size),
            adaptive_block_size=int(adaptive_block_size),
            adaptive_c=int(adaptive_c),
            min_component_area=int(min_component_area),
            bridge_gap_px=int(bridge_gap_px),
            max_preview_dim=int(max_vectorize_dim),
            input_mode=input_mode,
            stroke_max_width_px=float(stroke_max_width_px),
        )
        generate_clicked = st.button("Generate curves", type="primary", disabled=not (binary_ready and available), width="stretch")

    with result_col:
        if not image_path:
            st.info("Choose or input an image path to generate binary preview.")
        elif binary_ready:
            _render_binary_preview(st.session_state["vector_binary_preview"], st.session_state["vector_binary_analysis"])

    if image_path and not Path(image_path).is_file():
        st.error("Image path does not exist or is not a file")
        return

    if generate_clicked:
        source = Path(image_path)
        if not source.is_file():
            st.error("Image path does not exist or is not a file")
            return

        image = Image.open(source).convert("RGB")
        prefix = sanitize_filename(st.session_state.get("job_name") or infer_prefix_from_path(str(source), "image"), "image")
        st.session_state["job_name"] = prefix
        output = build_output_path(root_dir, "curves", prefix, "curves", "json")
        svg_output = build_output_path(root_dir, "curves", prefix, "strokes", "svg") if vectorizer in {"mixed_stroke_svg", "skeleton_stroke_svg", "outline_svg"} else None
        progress = st.progress(0, text="Start generating curves")

        def update_progress(value: float, text: str) -> None:
            progress.progress(int(value * 100), text=text)

        try:
            curve_list = vectorize_image_to_curve_list(
                np.array(image),
                threshold_method=threshold_method,  # type: ignore[arg-type]
                binary_threshold=int(threshold),
                blur_size=int(blur_size),
                adaptive_block_size=int(adaptive_block_size),
                adaptive_c=int(adaptive_c),
                min_component_area=int(min_component_area),
                bridge_gap_px=int(bridge_gap_px),
                min_curve_length_ratio=float(min_curve_ratio_pct) / 100.0,
                line_simplify_epsilon=float(sample_tolerance),
                area_simplify_epsilon=float(area_epsilon),
                min_path_length=int(min_path_length),
                smooth_iterations=int(smooth_iterations),
                max_vectorize_dim=int(max_vectorize_dim),
                stroke_max_width_px=float(stroke_max_width_px),
                source_image=str(source),
                vectorizer=vectorizer,  # type: ignore[arg-type]
                outline_engine=outline_engine,  # type: ignore[arg-type]
                svg_output_path=svg_output,
                work_dir=Path(root_dir) / "data" / "vectorization_temp",
                progress_callback=update_progress,
            )
        except VectorizationToolError as exc:
            st.error(str(exc))
            return
        except Exception as exc:
            st.error(f"Curve generation failed: {exc}")
            return

        if not curve_list.curves:
            st.error("No valid curves generated. Adjust binarization, classification, or filters.")
            return

        export_curves_json(curve_list, output)
        st.session_state["latest_curves_path"] = str(output)
        with result_col:
            st.success(f"Output: {output}")
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
            st.markdown("#### Latest curves file")
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
                st.warning(f"Curve file preview failed: {exc}")