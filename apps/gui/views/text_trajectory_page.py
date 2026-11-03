from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json

from apps.gui.parameter_ui import ui as st

from apps.gui.views.file_naming import build_output_path
from apps.gui.trajectory_player import render_trajectory_player
from apps.gui.views.trajectory_tools import planning_controls
from src.pipeline.export.json_exporter import export_curves_json, export_trajectory_json
from src.pipeline.text_trajectory import TextLayout, generate_text_curves, generate_text_trajectory


def render(config: dict, root_dir: str) -> None:
    st.subheader("文字轨迹")
    st.caption("中文按笔顺生成中心线；数字、英文使用单线字形。所有文字处理均在本机完成。")
    left, right = st.columns([1, 1.6])
    with left:
        text = st.text_area("文字内容", "", key="text_trajectory_input")
        st.caption("支持空格、换行及 ASCII 标点；中文标点和缺字会明确提示。中心位置作为文字字格区域的中心。")
        h = st.number_input("字格高度 mm", min_value=1.0, value=20.0, key="text_trajectory_height")
        gap = st.number_input("字距 mm", min_value=0.0, value=2.0, key="text_trajectory_gap")
        line_gap = st.number_input("行距 mm", min_value=0.0, value=5.0, key="text_trajectory_line_gap")
        planning = planning_controls(config, "text_trajectory")
        signature = (text, h, gap, line_gap, repr(asdict(planning)))
        if st.button("生成文字轨迹", type="primary", key="text_trajectory_generate",disabled=not text.strip()):
            try:
                curves = generate_text_curves(text, root_dir, TextLayout(h, gap, line_gap))
                trajectory = generate_text_trajectory(curves, planning)
                path = build_output_path(root_dir, "text_trajectories", text[:16], "trajectory", "json")
                export_curves_json(curves, path.with_name(path.stem.replace("_trajectory", "_curves") + ".json"))
                export_trajectory_json(trajectory, path)
                st.session_state["text_trajectory_result"] = (signature, str(path), trajectory)
                st.session_state["latest_trajectory_path"] = str(path)
            except (ValueError, OSError, ImportError, KeyError) as exc:
                st.error(str(exc))
    with right:
        result = st.session_state.get("text_trajectory_result")
        if not result:
            st.info("输入文字并生成，即可查看笔画路径和绘制顺序。")
            return
        saved_signature, path, trajectory = result
        stale = saved_signature != signature
        if stale:
            st.warning("参数已修改，下方仍是上次结果。请重新生成后再加入合成。")
        render_trajectory_player(trajectory,'text_result')
        st.caption(f"{trajectory.metadata['curve_count']} 笔画 · {len(trajectory.points)} 个轨迹点")
        with st.expander("字序与笔顺"):
            st.dataframe(trajectory.metadata["strokes"], hide_index=True, width="stretch")
        st.download_button("下载轨迹 JSON", json.dumps(trajectory.to_dict(),ensure_ascii=False,indent=2).encode(), Path(path).name, disabled=stale)
        if st.button("加入轨迹合成", disabled=stale, key="text_trajectory_add"):
            st.session_state["composition_pending_path"] = path
            st.session_state["pending_navigation"] = "轨迹合成"
            st.rerun()
        if st.button("前往数字文件导出", disabled=stale):
            st.session_state["latest_trajectory_path"] = path
            st.session_state["pending_navigation"] = "数字文件"
            st.rerun()
