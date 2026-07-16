from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from apps.gui.views.file_naming import build_output_path, sanitize_filename
from src.pipeline.image_generation import (
    SiliconFlowImageClient,
    SiliconFlowImageError,
    SiliconFlowImageRequest,
    build_retry_prompt,
    evaluate_traceable_line_image,
)


DEFAULT_IMAGE_MODEL = os.getenv("AI_IMAGE_MODEL", os.getenv("SILICONFLOW_IMAGE_MODEL", "Qwen/Qwen-Image"))
DEFAULT_NEGATIVE_PROMPT = (
    "robot, robotic arm, machine, mechanical arm, industrial robot, plotter, pen plotter, cnc, printer, "
    "human hand, artist, tool, pen, brush, camera, device, realistic, photorealistic, 3d, render, "
    "painting, watercolor, ink wash texture, color, grayscale, shadow, gradient, texture, background, scenery, "
    "filled areas, filled black shape, dense details, scales, fin details, eye details, complex ornament, "
    "tiny fragments, hatching, crosshatching, double outline, thick filled stroke, food, candy, syrup"
)


def T(value: str) -> str:
    return value.encode("ascii").decode("unicode_escape")


def _line_art_prompt(prompt: str) -> str:
    subject = (prompt or "").strip() or T("\\u9c7c")
    return (
        f"Subject: {subject}. "
        "Minimal black and white line drawing for tracing. "
        "One centered subject on a pure white background. "
        "Use very few smooth, long, continuous black strokes. "
        "Maximum 6 main strokes. Large simple silhouette, easy to recognize. "
        "Children's coloring book outline icon, not realistic. "
        "No color, no gray, no shading, no texture, no scene, no text. "
        "No tiny details, no hatching, no decorative pattern, no filled black area, no double outline. "
        "The result must be sparse and suitable for centerline tracing."
    )


def _quality_report_to_dict(report) -> dict:
    return {
        "accepted": bool(report.accepted),
        "score": int(report.score),
        "reasons": list(report.reasons),
        "metrics": dict(report.metrics),
    }


def _render_quality_report(report_dict: dict | None) -> None:
    if not report_dict:
        return
    metrics = report_dict.get("metrics", {})
    accepted = bool(report_dict.get("accepted"))
    score = int(report_dict.get("score", 0))
    if accepted:
        st.success(T("\\u53ef\\u7ed8\\u5236\\u6027\\u8bc4\\u5206\\uff1a") + f"{score}/100" + T("\\uff0c\\u901a\\u8fc7"))
    else:
        st.warning(T("\\u53ef\\u7ed8\\u5236\\u6027\\u8bc4\\u5206\\uff1a") + f"{score}/100" + T("\\uff0c\\u5efa\\u8bae\\u91cd\\u65b0\\u751f\\u6210\\u6216\\u6362\\u66f4\\u7b80\\u5355\\u4e3b\\u4f53"))
    reasons = report_dict.get("reasons", [])
    if reasons:
        st.caption(T("\\uff1b").join(str(item) for item in reasons))
    st.dataframe(
        [
            {T("\\u6307\\u6807"): T("\\u9ed1\\u8272\\u50cf\\u7d20\\u5360\\u6bd4"), T("\\u503c"): metrics.get("black_ratio")},
            {T("\\u6307\\u6807"): T("\\u6709\\u6548\\u8fde\\u901a\\u533a\\u57df"), T("\\u503c"): metrics.get("component_count")},
            {T("\\u6307\\u6807"): T("\\u77ed\\u5c0f\\u566a\\u58f0"), T("\\u503c"): metrics.get("small_component_count")},
            {T("\\u6307\\u6807"): T("\\u9762\\u72b6\\u586b\\u5145\\u5757"), T("\\u503c"): metrics.get("large_filled_component_count")},
            {T("\\u6307\\u6807"): T("\\u8fb9\\u7f18\\u5bc6\\u5ea6"), T("\\u503c"): metrics.get("detail_density")},
            {T("\\u6307\\u6807"): T("P90 \\u7b14\\u753b\\u5bbd\\u5ea6 px"), T("\\u503c"): metrics.get("p90_stroke_width_px")},
        ],
        width="stretch",
        hide_index=True,
        height=250,
    )


def render_image_generation_page(config: dict, root_dir: str, *, title: str | None = None) -> None:
    del config
    title = title or T("AI \\u751f\\u6210\\u56fe\\u7247")
    st.subheader(title)
    st.caption(T("\\u6839\\u636e\\u4e3b\\u4f53\\u63d0\\u793a\\u8bcd\\u751f\\u6210\\u6216\\u5bfc\\u5165\\u56fe\\u7247\\u3002\\u751f\\u6210\\u540e\\u4f1a\\u5148\\u505a\\u53ef\\u7ed8\\u5236\\u6027\\u7b5b\\u9009\\uff0c\\u518d\\u4f5c\\u4e3a\\u56fe\\u50cf\\u8f6c\\u66f2\\u7ebf\\u6a21\\u5757\\u7684\\u8f93\\u5165\\u3002"))

    image_dir = Path(root_dir) / "data" / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    control_col, preview_col = st.columns([0.85, 1.55])
    with control_col:
        job_name = st.text_input(T("\\u4efb\\u52a1\\u540d / \\u6587\\u4ef6\\u540d\\u524d\\u7f00"), value=st.session_state.get("job_name", ""))
        prompt = st.text_area(
            T("\\u4e3b\\u4f53\\u63d0\\u793a\\u8bcd"),
            value=st.session_state.get("design_prompt", T("\\u9c7c")),
            placeholder=T("\\u4f8b\\u5982\\uff1a\\u9c7c / \\u5154\\u5b50 / \\u8774\\u8776\\u3002\\u8fd9\\u91cc\\u53ea\\u5199\\u4e3b\\u4f53\\uff0c\\u8d8a\\u77ed\\u8d8a\\u597d\\u3002"),
            height=76,
        )
        st.session_state["design_prompt"] = prompt

        st.markdown("#### " + T("AI \\u751f\\u6210\\u56fe\\u7247"))
        api_key = st.text_input(
            "API Key",
            type="password",
            value="",
            help=T("\\u7559\\u7a7a\\u5219\\u8bfb\\u53d6\\u73af\\u5883\\u53d8\\u91cf AI_IMAGE_API_KEY\\uff1b\\u4e0d\\u4f1a\\u5199\\u5165\\u914d\\u7f6e\\u6587\\u4ef6\\u3002"),
        )
        model = st.text_input(
            T("\\u751f\\u56fe\\u6a21\\u578b"),
            value=DEFAULT_IMAGE_MODEL,
            help=T("\\u63a8\\u8350\\u5148\\u7528 Qwen/Qwen-Image\\uff1b\\u5982\\u679c\\u670d\\u52a1\\u7aef\\u6682\\u4e0d\\u652f\\u6301\\uff0c\\u53ef\\u6539\\u56de Kwai-Kolors/Kolors\\u3002"),
        )
        size = st.selectbox(T("\\u56fe\\u7247\\u5c3a\\u5bf8"), ["768x768", "512x512", "1024x1024"], index=0)
        steps = st.slider(T("\\u751f\\u6210\\u6b65\\u6570"), 8, 40, 16)
        seed_text = st.text_input(T("Seed\\uff08\\u53ef\\u7a7a\\uff09"), value="")
        quality_check = st.checkbox(T("\\u751f\\u6210\\u540e\\u81ea\\u52a8\\u7b5b\\u9009\\u53ef\\u7ed8\\u5236\\u6027"), value=True)
        max_attempts = st.slider(T("\\u4e0d\\u5408\\u683c\\u81ea\\u52a8\\u91cd\\u8bd5\\u6b21\\u6570"), 1, 4, 3, disabled=not quality_check)

        final_prompt = _line_art_prompt(prompt)
        with st.expander(T("\\u5b9e\\u9645\\u63d0\\u4ea4\\u63d0\\u793a\\u8bcd"), expanded=False):
            st.code(final_prompt)
            st.caption(T("\\u8fd9\\u91cc\\u53ea\\u63d0\\u4ea4\\u6781\\u7b80\\u9ed1\\u767d\\u7ebf\\u7a3f\\u7ea6\\u675f\\uff0c\\u4e0d\\u628a\\u7cd6\\u753b\\u3001\\u673a\\u5668\\u4eba\\u3001\\u673a\\u68b0\\u81c2\\u7b49\\u8bcd\\u4ea4\\u7ed9\\u751f\\u56fe\\u6a21\\u578b\\u3002"))
        generate_image = st.button(T("\\u751f\\u6210\\u56fe\\u7247"), type="primary", width="stretch")

        st.divider()
        st.markdown("#### " + T("\\u6216\\u4e0a\\u4f20\\u56fe\\u7247"))
        uploaded = st.file_uploader(T("\\u4e0a\\u4f20\\u56fe\\u7247"), type=["png", "jpg", "jpeg", "bmp"])
        save_upload = st.button(T("\\u4fdd\\u5b58\\u4e0a\\u4f20\\u56fe\\u7247"), width="stretch", disabled=uploaded is None)

    if generate_image:
        prefix = sanitize_filename(job_name or "ai_image", fallback="ai_image")
        st.session_state["job_name"] = prefix
        seed = int(seed_text) if seed_text.strip().isdigit() else None
        attempts = int(max_attempts) if quality_check else 1
        client = SiliconFlowImageClient(api_key=api_key.strip() or None)
        progress = st.progress(0, text=T("\\u51c6\\u5907\\u751f\\u6210\\u56fe\\u7247"))
        attempt_rows: list[dict] = []
        best_path: Path | None = None
        best_report = None
        accepted_path: Path | None = None
        accepted_report = None

        try:
            for attempt in range(1, attempts + 1):
                progress.progress((attempt - 1) / attempts, text=T("\\u7b2c") + f" {attempt}/{attempts} " + T("\\u6b21\\u751f\\u6210"))
                output = build_output_path(root_dir, "images", prefix, f"ai_a{attempt}", "png")
                request = SiliconFlowImageRequest(
                    prompt=build_retry_prompt(final_prompt, attempt),
                    model=model.strip() or DEFAULT_IMAGE_MODEL,
                    size=size,
                    negative_prompt=DEFAULT_NEGATIVE_PROMPT,
                    steps=int(steps),
                    seed=(seed + attempt - 1) if seed is not None else None,
                )
                client.generate_and_save(request, output)
                if quality_check:
                    report = evaluate_traceable_line_image(output)
                    attempt_rows.append(
                        {
                            T("\\u5c1d\\u8bd5"): attempt,
                            T("\\u8bc4\\u5206"): report.score,
                            T("\\u7ed3\\u679c"): T("\\u901a\\u8fc7") if report.accepted else T("\\u672a\\u901a\\u8fc7"),
                            T("\\u539f\\u56e0"): T("\\uff1b").join(report.reasons),
                            T("\\u6587\\u4ef6"): str(output),
                        }
                    )
                    if best_report is None or report.score > best_report.score:
                        best_report = report
                        best_path = output
                    if report.accepted:
                        accepted_path = output
                        accepted_report = report
                        break
                else:
                    accepted_path = output
                    break
        except SiliconFlowImageError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(T("\\u751f\\u6210\\u5931\\u8d25\\uff1a") + str(exc))
        else:
            if quality_check and attempt_rows:
                st.dataframe(attempt_rows, width="stretch", hide_index=True, height=min(180, 38 + 36 * len(attempt_rows)))
            final_path = accepted_path or best_path
            final_report = accepted_report or best_report
            if final_path is not None:
                st.session_state["latest_image_path"] = str(final_path)
                st.session_state["latest_image_quality"] = _quality_report_to_dict(final_report) if final_report else None
                if accepted_path is not None or not quality_check:
                    st.success(T("\\u5df2\\u751f\\u6210\\uff1a") + str(final_path))
                else:
                    st.warning(T("\\u672a\\u627e\\u5230\\u5b8c\\u5168\\u5408\\u683c\\u56fe\\u7247\\uff0c\\u5df2\\u4fdd\\u7559\\u8bc4\\u5206\\u6700\\u9ad8\\u7684\\u4e00\\u5f20\\uff1a") + str(final_path))
            progress.progress(1.0, text=T("\\u751f\\u6210\\u5b8c\\u6210"))

    if uploaded and save_upload:
        suffix = Path(uploaded.name).suffix.lower() or ".png"
        prefix = sanitize_filename(job_name or Path(uploaded.name).stem, fallback="input")
        st.session_state["job_name"] = prefix
        output = build_output_path(root_dir, "images", prefix, "input", suffix)
        output.write_bytes(uploaded.getbuffer())
        st.session_state["latest_image_path"] = str(output)
        try:
            st.session_state["latest_image_quality"] = _quality_report_to_dict(evaluate_traceable_line_image(output))
        except Exception:
            st.session_state["latest_image_quality"] = None
        st.success(T("\\u5df2\\u4fdd\\u5b58\\uff1a") + str(output))

    with preview_col:
        latest = st.session_state.get("latest_image_path")
        if latest and Path(latest).exists():
            st.markdown("#### " + T("\\u5f53\\u524d\\u8f93\\u5165\\u56fe\\u7247"))
            st.code(latest)
            st.image(latest, width="stretch")
            _render_quality_report(st.session_state.get("latest_image_quality"))
        else:
            st.info(T("\\u751f\\u6210\\u6216\\u4e0a\\u4f20\\u56fe\\u7247\\u540e\\uff0c\\u4f1a\\u5728\\u8fd9\\u91cc\\u663e\\u793a\\uff0c\\u5e76\\u4f5c\\u4e3a\\u56fe\\u50cf\\u8f6c\\u66f2\\u7ebf\\u6a21\\u5757\\u7684\\u8f93\\u5165\\u3002"))


def render(config: dict, root_dir: str) -> None:
    render_image_generation_page(config, root_dir, title=T("\\u8bbe\\u8ba1\\u8f93\\u5165"))
