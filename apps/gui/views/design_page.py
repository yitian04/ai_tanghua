from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

from apps.gui.views.file_naming import build_output_path, sanitize_filename


def render(config: dict, root_dir: str) -> None:
    del config
    st.subheader("设计输入")
    st.caption("本页只产生图片文件，不连接机器人。")

    image_dir = Path(root_dir) / "data" / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    job_name = st.text_input("任务名 / 文件名前缀（可选）", value=st.session_state.get("job_name", ""))
    prompt = st.text_area("提示词", placeholder="例如：一只线条简洁的兔子糖画", height=90)
    uploaded = st.file_uploader("上传图片", type=["png", "jpg", "jpeg", "bmp"])

    if uploaded and st.button("保存为输入图片", type="primary"):
        suffix = Path(uploaded.name).suffix.lower() or ".png"
        prefix = sanitize_filename(job_name or Path(uploaded.name).stem, fallback="input")
        st.session_state["job_name"] = prefix
        output = build_output_path(root_dir, "images", prefix, "input", suffix)
        output.write_bytes(uploaded.getbuffer())
        st.success(f"已保存：{output}")
        st.session_state["latest_image_path"] = str(output)
        st.image(str(output), caption="当前输入图片")

    if prompt:
        st.info("AI 生图接口尚未绑定。当前阶段建议先上传图片，后续可在这里接 ComfyUI/其他生图 provider。")

    latest = st.session_state.get("latest_image_path")
    if latest and Path(latest).exists():
        st.markdown("#### 最近图片")
        st.code(latest)
        st.image(latest, width="stretch")
