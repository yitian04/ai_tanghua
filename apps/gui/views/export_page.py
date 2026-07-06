from __future__ import annotations

from pathlib import Path

import streamlit as st

from apps.gui.views.ur_execution_controls import (
    execution_profile_caption,
    render_urscript_execution_profile,
    save_urscript_execution_defaults,
)
from src.pipeline.export.csv_exporter import export_trajectory_csv
from src.pipeline.export.gcode_exporter import export_trajectory_gcode
from src.pipeline.export.json_exporter import load_trajectory_json
from src.pipeline.export.urscript_exporter import export_trajectory_urscript


def _load_trajectory_or_error(trajectory_path: str):
    source = Path(trajectory_path)
    if not source.exists():
        st.error("轨迹文件不存在")
        return None, None
    return source, load_trajectory_json(source)


def render(config: dict, root_dir: str) -> None:
    st.subheader("数字文件")
    st.caption("trajectory.json 可分别导出为 CSV、G-code 和可导入 PolyScope 的 URP。这里仍然只生成文件，不连接机械臂。")

    trajectory_path = st.text_input("轨迹 JSON 路径", value=st.session_state.get("latest_trajectory_path", ""))
    profile = render_urscript_execution_profile(config)
    st.caption(execution_profile_caption(profile))
    if st.button("设为URScript默认值", width="stretch"):
        saved_path = save_urscript_execution_defaults(root_dir, profile)
        st.success(f"已保存为 URScript 默认值：{saved_path}")

    export_dir = Path(root_dir) / "data" / "exports"
    btn_csv, btn_gcode, btn_urp = st.columns(3)

    if btn_csv.button("导出 CSV", type="primary", disabled=not trajectory_path, width="stretch"):
        source, trajectory = _load_trajectory_or_error(trajectory_path)
        if trajectory is None:
            return
        csv_path = export_trajectory_csv(trajectory, export_dir / f"{source.stem}.csv")
        st.success("CSV 导出完成")
        st.code(str(csv_path))

    if btn_gcode.button("导出 G-code", type="primary", disabled=not trajectory_path, width="stretch"):
        source, trajectory = _load_trajectory_or_error(trajectory_path)
        if trajectory is None:
            return
        gcode_path = export_trajectory_gcode(trajectory, export_dir / f"{source.stem}.gcode")
        st.success("G-code 导出完成")
        st.code(str(gcode_path))

    if btn_urp.button("导出 URP", type="primary", disabled=not trajectory_path, width="stretch"):
        source, trajectory = _load_trajectory_or_error(trajectory_path)
        if trajectory is None:
            return
        urp_path = export_trajectory_urscript(
            trajectory,
            export_dir / f"{source.stem}.urp",
            output_pin=profile.output_pin,
            **profile.export_options(),
        )
        st.success("URP 导出完成")
        st.code(str(urp_path))

    if export_dir.exists():
        files = sorted(export_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
        if files:
            st.markdown("#### 最近导出")
            for file in files:
                st.text(str(file))
