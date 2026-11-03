from __future__ import annotations

from pathlib import Path

from apps.gui.parameter_ui import ui as st
from apps.gui.asset_library import file_input, image_input
from apps.gui.views.file_naming import build_output_path

from apps.gui.views.ur_execution_controls import (
    execution_profile_caption,
    render_urscript_execution_profile,
    save_urscript_execution_defaults,
)
from src.pipeline.export.csv_exporter import export_trajectory_csv
from src.pipeline.export.gcode_exporter import export_trajectory_gcode
from src.robot.job_loader import load_trajectory_file as load_trajectory_json
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

    trajectory_path = file_input(root_dir, "export", "轨迹输入", {"trajectory"}, candidate=st.session_state.get("latest_trajectory_path"))
    profile = render_urscript_execution_profile(config,root_dir)
    if st.button("设为URScript默认值", width="stretch"):
        saved_path = save_urscript_execution_defaults(root_dir, profile)
        st.success(f"已保存为 URScript 默认值：{saved_path}")

    from src.robot.ur5.path_config import PathStore,validate_config
    route=None
    try:
        robot_ip=st.session_state.get('robot_ip',config.get('robot',{}).get('ip','192.168.1.100'))
        route=PathStore(root_dir,robot_ip).load();validate_config(route)
    except (ValueError,OSError):route=None
    from dataclasses import replace
    if route: profile=replace(profile,output_pin=route['output_pin'])
    st.caption(execution_profile_caption(profile))
    st.caption('URP 需要已验证的示教路径及配套任务服务；文件本身不会建立电脑心跳，禁止脱离任务服务单独执行。')
    export_dir = Path(root_dir) / "data" / "exports"
    btn_csv, btn_gcode, btn_urp = st.columns(3)

    if btn_csv.button("导出 CSV", type="primary", disabled=not trajectory_path, width="stretch"):
        source, trajectory = _load_trajectory_or_error(trajectory_path)
        if trajectory is None:
            return
        csv_path = export_trajectory_csv(trajectory, build_output_path(root_dir,'exports',source.stem,'export','csv'))
        st.success("CSV 导出完成")
        st.code(str(csv_path))

    if btn_gcode.button("导出 G-code", type="primary", disabled=not trajectory_path, width="stretch"):
        source, trajectory = _load_trajectory_or_error(trajectory_path)
        if trajectory is None:
            return
        gcode_path = export_trajectory_gcode(trajectory, build_output_path(root_dir,'exports',source.stem,'export','gcode'))
        st.success("G-code 导出完成")
        st.code(str(gcode_path))

    if btn_urp.button("导出 URP", type="primary", disabled=not trajectory_path or route is None, width="stretch"):
        source, trajectory = _load_trajectory_or_error(trajectory_path)
        if trajectory is None:
            return
        urp_path = export_trajectory_urscript(
            trajectory,
            build_output_path(root_dir,'exports',source.stem,'export','urp'),
            output_pin=route["output_pin"],
            path_config=route,
            **profile.export_options(),
        )
        st.success("URP 导出完成")
        st.code(str(urp_path))

    from apps.gui.workspace import draft
    current=draft('export')
    if current:
        for artifact in current.artifacts:st.download_button('下载 '+artifact.name,artifact.payload,artifact.name)

    if export_dir.exists():
        files = sorted(export_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
        if files:
            st.markdown("#### 最近导出")
            for file in files:
                st.text(str(file))
