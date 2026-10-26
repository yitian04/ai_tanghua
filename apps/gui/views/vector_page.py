from __future__ import annotations

import hashlib
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st
from PIL import Image

from apps.gui.views.file_naming import build_output_path, infer_prefix_from_path, sanitize_filename
from apps.gui.plot_fonts import configure_matplotlib_chinese_font
from src.core.models import CurveList
from src.modules.image_process_module import create_binary_preview, vectorize_image_to_curve_list
from src.pipeline.export.json_exporter import export_curves_json, load_curves_json
from src.pipeline.vectorization import VectorizationToolError, available_vectorization_tools


METHOD_LABELS = {
    "自动识别线条与面域": "mixed_stroke_svg",
    "仅提取线条骨架": "skeleton_stroke_svg",
    "仅提取面域轮廓": "outline_svg",
    "OpenCV 基础模式": "opencv_fallback",
}

THRESHOLD_LABELS = {
    "Otsu 自动阈值": "otsu",
    "自适应阈值": "adaptive",
    "手动阈值": "manual",
}

OUTLINE_ENGINE_LABELS = {
    "自动选择": "auto",
    "VTracer": "vtracer",
    "Potrace": "potrace",
}


def _plot_curves(
    curve_list: CurveList,
    image_path: str | None = None,
    show_source_image: bool = True,
    source_alpha: float = 0.35,
):
    configure_matplotlib_chinese_font()
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
    ax.set_title("曲线预览", fontsize=9)
    ax.set_xlabel("图像 X 坐标 / 像素")
    ax.set_ylabel("图像 Y 坐标 / 像素")
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
    col_a.metric("曲线数", len(curve_list.curves))
    col_b.metric("点数", total_points)
    frame_label = "图像像素坐标" if curve_list.coordinate_frame == "image_px" else curve_list.coordinate_frame
    col_c.metric("坐标系", frame_label)

    source_svg = curve_list.metadata.get("stroke_svg_output_path") or curve_list.metadata.get("source_svg") or curve_list.metadata.get("svg_output_path")
    if source_svg:
        st.caption(f"SVG: {source_svg}")

    rows = [
        {
            "曲线编号": curve.curve_id,
            "点数": len(curve.points),
            "起点": curve.start(),
            "终点": curve.end(),
            "是否闭合": curve.closed,
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
    st.markdown("#### 二值化与分类预览")
    st.image(Image.fromarray(preview), width="stretch")
    if analysis.get("input_mode") == "line_only":
        st.caption(
            f"连通区域={analysis['component_count']}；全部按线条处理；"
            f"90%分位线宽={float(analysis['p90_stroke_width_px']):.1f}像素。"
            "黑色表示将要提取的线条骨架，不进行面域识别。"
        )
    else:
        st.caption(
            f"连通区域={analysis['component_count']}；"
            f"线条区域={analysis['line_component_count']}；"
            f"面域={analysis['area_component_count']}；"
            f"90%分位线宽={float(analysis['p90_stroke_width_px']):.1f}像素。"
            "黑色表示线条骨架，灰色表示面域轮廓。"
        )
    original_size = analysis.get("original_image_size")
    processing_size = analysis.get("processing_image_size")
    if original_size and processing_size:
        st.caption(f"处理尺寸：{original_size[0]}×{original_size[1]} → {processing_size[0]}×{processing_size[1]}")

    rows = [
        {
            "类型": "线条" if item["content_type"] == "line" else "面域",
            "X": item["x"],
            "Y": item["y"],
            "宽": item["width"],
            "高": item["height"],
            "面积": item["area"],
            "长宽比": round(float(item["bbox_aspect"]), 2),
            "填充率": round(float(item["fill_ratio"]), 2),
            "90%分位线宽": round(float(item["p90_stroke_width_px"]), 1),
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
        return True, "线条骨架提取无需安装外部工具。"
    if method == "mixed_stroke_svg":
        if tools.get("vtracer") or tools.get("potrace"):
            return True, "线条使用骨架提取，面域使用 VTracer/Potrace 提取轮廓。"
        return True, "线条可正常提取；面域将使用 OpenCV 轮廓作为备用方案。"
    if outline_engine == "vtracer":
        return bool(tools.get("vtracer")), f"VTracer：{tools.get('vtracer') or '未找到'}"
    if outline_engine == "potrace":
        return bool(tools.get("potrace")), f"Potrace：{tools.get('potrace') or '未找到'}"
    if tools.get("vtracer"):
        return True, f"自动使用 VTracer：{tools['vtracer']}"
    if tools.get("potrace"):
        return True, f"自动使用 Potrace：{tools['potrace']}"
    return False, "未找到 VTracer/Potrace。请将可执行文件放入 tools/VTracer/ 或 tools/Potrace/。"


def render(config: dict, root_dir: str) -> None:
    del config
    st.subheader("图像转曲线")
    st.caption("上传或选择图像，生成 CurveList JSON，并可选输出仅含笔画的 SVG。本页面不会连接机械臂。")

    generated_this_run = False
    tools = available_vectorization_tools()
    control_col, result_col = st.columns([0.85, 1.65])

    with control_col:
        st.markdown("#### 图像输入")
        uploaded_image = st.file_uploader(
            "上传本地图像",
            type=["png", "jpg", "jpeg", "webp", "bmp"],
            help="支持 PNG、JPG、JPEG、WEBP 和 BMP；上传后会自动保存到项目的 data/images/uploads 目录。",
            key="vector_image_upload",
        )
        if "vector_image_path" not in st.session_state:
            st.session_state["vector_image_path"] = st.session_state.get("latest_image_path", "")
        if uploaded_image is not None:
            payload = uploaded_image.getvalue()
            digest = hashlib.sha256(payload).hexdigest()[:10]
            original_name = Path(uploaded_image.name)
            safe_stem = sanitize_filename(original_name.stem, "uploaded_image")
            extension = original_name.suffix.lower() or ".png"
            upload_dir = Path(root_dir) / "data" / "images" / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            upload_path = upload_dir / f"{safe_stem}_{digest}{extension}"
            if not upload_path.exists():
                upload_path.write_bytes(payload)
            st.session_state["vector_image_path"] = str(upload_path)
            st.session_state["latest_image_path"] = str(upload_path)
            st.caption(f"已载入：{uploaded_image.name}")

        image_path = st.text_input(
            "或输入图像文件路径",
            key="vector_image_path",
            help="也可以直接填写本机已有图像的完整路径。",
        )
        show_source_image = st.checkbox("在曲线上叠加原图", value=True)
        source_alpha = st.slider("原图透明度", 0.0, 1.0, 0.35, 0.05, disabled=not show_source_image)

        st.markdown("#### 转换参数")
        method_label = st.selectbox(
            "曲线提取方式",
            list(METHOD_LABELS.keys()),
            index=1,
            key="vectorizer_method_label",
            help="AI 线稿默认全部按线条骨架处理，不再把相邻线条识别为面域。",
        )
        vectorizer = METHOD_LABELS[method_label]
        input_mode = _preview_mode(vectorizer)
        outline_engine = "auto"
        if vectorizer in {"outline_svg", "mixed_stroke_svg"}:
            outline_engine_label = st.selectbox("SVG 轮廓引擎", list(OUTLINE_ENGINE_LABELS.keys()), index=0)
            outline_engine = OUTLINE_ENGINE_LABELS[outline_engine_label]

        available, status_text = _method_available(vectorizer, outline_engine, tools)
        if available:
            st.caption(status_text)
        else:
            st.warning(status_text)
        if vectorizer == "skeleton_stroke_svg":
            st.info("当前模式会把全部有效黑色区域视为线条并提取中心骨架，不执行面域轮廓处理。")

        threshold_label = st.selectbox("二值化方式", list(THRESHOLD_LABELS.keys()), index=0)
        threshold_method = THRESHOLD_LABELS[threshold_label]
        threshold = st.slider("手动阈值", 0, 255, 128, disabled=threshold_method != "manual")
        blur_size = st.selectbox(
            "模糊核大小",
            [0, 3, 5, 7],
            index=0,
            help="AI 线稿默认不模糊，以免相邻排线粘连。",
        )
        adaptive_block_size = st.selectbox("自适应窗口大小", [15, 21, 31, 45, 61], index=2, disabled=threshold_method != "adaptive")
        adaptive_c = st.slider("自适应阈值偏移量 C", -10, 20, 5, disabled=threshold_method != "adaptive")
        min_component_area = st.number_input("最小连通区域面积", min_value=1, max_value=100000, value=20, step=5)
        bridge_gap_px = st.slider(
            "连接小断点（像素）",
            0,
            6,
            0,
            help="默认关闭，避免把相邻排线横向连接；只有确实存在微小断口时再逐级增加。",
        )
        stroke_max_width_px = st.number_input(
            "自动分类最大线宽（像素）",
            min_value=1.0,
            max_value=200.0,
            value=18.0,
            step=1.0,
            disabled=vectorizer in {"outline_svg", "skeleton_stroke_svg"},
            help="仅在“自动识别线条与面域”模式中使用。",
        )
        sample_tolerance = st.number_input("曲线采样与简化容差（像素）", min_value=0.2, max_value=20.0, value=1.2, step=0.2)
        min_curve_ratio_pct = st.number_input(
            "短曲线过滤比例（%）",
            min_value=0.0,
            max_value=10.0,
            value=0.3,
            step=0.1,
            help="降低默认过滤比例，保留构成规则排线的短线。",
        )
        max_vectorize_dim = st.number_input("处理图像最大边长", min_value=256, max_value=4096, value=1024, step=128)

        with st.expander("骨架提取高级参数", expanded=vectorizer in {"mixed_stroke_svg", "skeleton_stroke_svg"}):
            if vectorizer in {"mixed_stroke_svg", "outline_svg"}:
                area_epsilon = st.number_input("面域简化容差（像素）", min_value=0.1, max_value=30.0, value=2.0, step=0.5)
            else:
                area_epsilon = 2.0
            smooth_iterations = st.slider("线条平滑次数", 0, 3, 0)
            min_path_length = st.number_input("骨架最短路径长度", min_value=2, max_value=1000, value=8, step=1)

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
        generate_clicked = st.button("生成曲线", type="primary", disabled=not (binary_ready and available), width="stretch")

    with result_col:
        if not image_path:
            st.info("请上传本地图像，或输入已有图像的完整路径。")
        elif binary_ready:
            _render_binary_preview(st.session_state["vector_binary_preview"], st.session_state["vector_binary_analysis"])

    if image_path and not Path(image_path).is_file():
        st.error("图像路径不存在，或该路径不是文件。")
        return

    if generate_clicked:
        source = Path(image_path)
        if not source.is_file():
            st.error("图像路径不存在，或该路径不是文件。")
            return

        image = Image.open(source).convert("RGB")
        prefix = sanitize_filename(st.session_state.get("job_name") or infer_prefix_from_path(str(source), "image"), "image")
        st.session_state["job_name"] = prefix
        output = build_output_path(root_dir, "curves", prefix, "curves", "json")
        svg_output = build_output_path(root_dir, "curves", prefix, "strokes", "svg") if vectorizer in {"mixed_stroke_svg", "skeleton_stroke_svg", "outline_svg"} else None
        progress = st.progress(0, text="开始生成曲线")

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
            st.error(f"曲线生成失败：{exc}")
            return

        if not curve_list.curves:
            st.error("没有生成有效曲线，请调整二值化、区域分类或过滤参数。")
            return

        export_curves_json(curve_list, output)
        st.session_state["latest_curves_path"] = str(output)
        with result_col:
            st.success(f"曲线文件已输出：{output}")
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
            st.markdown("#### 最近生成的曲线文件")
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
