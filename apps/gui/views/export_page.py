from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.pipeline.export.csv_exporter import export_trajectory_csv
from src.pipeline.export.gcode_exporter import export_trajectory_gcode
from src.pipeline.export.json_exporter import load_trajectory_json


def render(config: dict, root_dir: str) -> None:
    del config
    st.subheader("数字文件")
    st.caption("trajectory.json 可导出为 CSV/G-code。这里仍然不连接机器人。")

    trajectory_path = st.text_input("轨迹 JSON 路径", value=st.session_state.get("latest_trajectory_path", ""))
    if st.button("导出 CSV 和 G-code", type="primary", disabled=not trajectory_path):
        source = Path(trajectory_path)
        if not source.exists():
            st.error("轨迹文件不存在")
            return
        trajectory = load_trajectory_json(source)
        export_dir = Path(root_dir) / "data" / "exports"
        csv_path = export_trajectory_csv(trajectory, export_dir / f"{source.stem}.csv")
        gcode_path = export_trajectory_gcode(trajectory, export_dir / f"{source.stem}.gcode")
        st.success("导出完成")
        st.code(str(csv_path))
        st.code(str(gcode_path))

    export_dir = Path(root_dir) / "data" / "exports"
    if export_dir.exists():
        files = sorted(export_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
        if files:
            st.markdown("#### 最近导出")
            for file in files:
                st.text(str(file))
