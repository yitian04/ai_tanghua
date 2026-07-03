from __future__ import annotations

import time
from pathlib import Path
from typing import Dict

import streamlit as st

from src.robot.job_loader import load_trajectory_file
from src.robot.mock import MockRobotAdapter
from src.robot.ur5 import UR5RobotAdapter


def _create_ur5(config: Dict) -> UR5RobotAdapter:
    robot_config = config.get("robot", {})
    return UR5RobotAdapter(
        dashboard_port=int(robot_config.get("dashboard_port", 29999)),
        script_port=int(robot_config.get("script_port", 30002)),
        timeout=float(robot_config.get("timeout", 5)),
    )


def _add_log(message: str) -> None:
    if "robot_log" not in st.session_state:
        st.session_state.robot_log = []
    st.session_state.robot_log.insert(0, f"{time.strftime('%H:%M:%S')}  {message}")
    st.session_state.robot_log = st.session_state.robot_log[:50]


def _init_state(config: Dict) -> None:
    robot_config = config.get("robot", {})
    if "robot_ip" not in st.session_state:
        st.session_state.robot_ip = robot_config.get("ip", "192.168.1.100")
    if "robot_status" not in st.session_state:
        st.session_state.robot_status = {}
    if "connection_test" not in st.session_state:
        st.session_state.connection_test = {"tested": False, "ping_ok": False, "dashboard_ok": False, "message": "未测试"}
    if "motion_in_progress" not in st.session_state:
        st.session_state.motion_in_progress = False
    if "storage_confirmed" not in st.session_state:
        st.session_state.storage_confirmed = False
    if "ur5_robot" not in st.session_state or not hasattr(st.session_state.ur5_robot, "get_realtime_state"):
        st.session_state.ur5_robot = _create_ur5(config)
    st.session_state.ur5_robot.set_ip(st.session_state.robot_ip)


def _sync_ip() -> str:
    ip = (st.session_state.get("robot_ip_input", st.session_state.get("robot_ip", "")) or "").strip()
    if ip != st.session_state.get("robot_ip", ""):
        st.session_state.robot_status = {}
        st.session_state.connection_test = {"tested": False, "ping_ok": False, "dashboard_ok": False, "message": "IP 已变更，待检测"}
    st.session_state.robot_ip = ip
    st.session_state.ur5_robot.set_ip(ip)
    return ip


def _refresh_status() -> None:
    _sync_ip()
    st.session_state.robot_status = st.session_state.ur5_robot.get_robot_info()


def _render_realtime_state() -> None:
    _sync_ip()
    realtime = st.session_state.ur5_robot.get_realtime_state()
    st.session_state.realtime_state = realtime
    if not realtime.get("ok"):
        st.warning(f"实时数据读取失败：{realtime.get('error', 'unknown')}")
        return

    tcp = realtime.get("tcp_pose_mm_deg")
    joints = realtime.get("joint_degrees", [])
    speeds = realtime.get("joint_speed_degrees", [])
    if tcp:
        st.markdown("#### TCP 位姿")
        labels = ["X mm", "Y mm", "Z mm", "Rx deg", "Ry deg", "Rz deg"]
        for col, label, value in zip(st.columns(6), labels, tcp):
            col.metric(label, f"{value:.2f}")
    if joints:
        st.markdown("#### 六轴角度")
        for idx, (col, value) in enumerate(zip(st.columns(6), joints), start=1):
            speed = speeds[idx - 1] if idx - 1 < len(speeds) else 0.0
            col.metric(f"J{idx}", f"{value:.2f}°", delta=f"{speed:.2f}°/s")


def _render_ur5_control(config: Dict) -> None:
    del config
    robot = st.session_state.ur5_robot
    ip_ready = bool(st.session_state.get("robot_ip", "").strip())
    locked = bool(st.session_state.get("motion_in_progress", False))
    controls_disabled = (not ip_ready) or locked

    st.markdown("### UR5 控制")
    st.caption("这里是后半段机器人适配层；前面的设计、曲线、轨迹文件生成不依赖本页。")

    top_left, top_right = st.columns([2, 1])
    with top_left:
        st.text_input("机器人 IP 地址", value=st.session_state.robot_ip, key="robot_ip_input")
        _sync_ip()
    with top_right:
        test = st.session_state.connection_test
        st.metric("Dashboard", "可用" if test.get("dashboard_ok") else "未确认/不可用")
        st.caption(f"Ping 仅参考：{'通' if test.get('ping_ok') else '不通/未知'}")

    if locked:
        st.error("机械臂运动中，其他操作已锁定。")

    action_cols = st.columns(3)
    with action_cols[0]:
        if st.button("测试 Dashboard", use_container_width=True, disabled=controls_disabled):
            result = robot.test_connection()
            st.session_state.connection_test = {
                "tested": True,
                "ok": bool(result.get("ok")),
                "ping_ok": bool(result.get("ping_ok")),
                "dashboard_ok": bool(result.get("dashboard_ok")),
                "message": result.get("robotmode") or result.get("greeting") or result.get("error") or "unknown",
                "ping_output": result.get("ping_output", ""),
            }
            _add_log(f"连接检测：dashboard={'可用' if result.get('dashboard_ok') else '不可用'}")
    with action_cols[1]:
        if st.button("刷新状态", use_container_width=True, disabled=controls_disabled):
            _refresh_status()
            _add_log("状态已刷新")
    with action_cols[2]:
        if st.button("停止程序", use_container_width=True, disabled=controls_disabled):
            ok = robot.stop_program()
            _add_log("停止程序命令已发送" if ok else f"停止失败：{robot.last_dashboard_response}")
            _refresh_status()

    st.divider()
    st.markdown("### 电源与使能")
    power_cols = st.columns(3)
    with power_cols[0]:
        if st.button("上电 Power On", use_container_width=True, disabled=controls_disabled, type="primary"):
            ok = robot.power_on()
            _add_log("上电命令已发送" if ok else f"上电失败：{robot.last_dashboard_response}")
            time.sleep(1.0)
            _refresh_status()
    with power_cols[1]:
        if st.button("使能/松刹车", use_container_width=True, disabled=controls_disabled, type="primary"):
            ok = robot.brake_release()
            _add_log("使能/松刹车命令已发送" if ok else f"使能失败：{robot.last_dashboard_response}")
            time.sleep(1.0)
            _refresh_status()
    with power_cols[2]:
        if st.button("下电 Power Off", use_container_width=True, disabled=controls_disabled):
            ok = robot.power_off()
            _add_log("下电命令已发送" if ok else f"下电失败：{robot.last_dashboard_response}")
            time.sleep(1.0)
            _refresh_status()

    st.divider()
    st.markdown("### 状态")
    status = st.session_state.robot_status or {"dashboard_ok": False, "robot_mode": "未刷新", "program_state": "未刷新", "safety_status": "未刷新"}
    cols = st.columns(5)
    cols[0].metric("Ping 仅参考", "通" if status.get("ping_ok") else "未知/不通")
    cols[1].metric("Dashboard", "可用" if status.get("dashboard_ok") else "不可用")
    cols[2].metric("机器人模式", status.get("robot_mode", "unknown"))
    cols[3].metric("程序状态", status.get("program_state", "unknown"))
    cols[4].metric("安全状态", status.get("safety_status", "unknown"))

    st.divider()
    st.markdown("### 收纳动作")
    st.caption("目标六轴角度：J1=95°，J2=-100°，J3=157°，J4=-60°，J5=0°，J6=20°。执行速度限制为 10%。")
    st.session_state.storage_confirmed = st.checkbox("我确认机械臂周围无人、无障碍物，允许低速回到收纳状态", value=st.session_state.storage_confirmed, disabled=locked)
    if st.button("回到收纳状态", use_container_width=True, type="primary", disabled=controls_disabled or not st.session_state.storage_confirmed):
        st.session_state.motion_in_progress = True
        try:
            result = robot.movej_degrees([95, -100, 157, -60, 0, 20], speed_fraction=0.1)
            _add_log(result.get("message", "收纳动作完成" if result.get("ok") else "收纳动作失败"))
            if result.get("ok"):
                st.success(result.get("message", "收纳动作完成"))
            else:
                st.error(result.get("message", "收纳动作失败"))
            _refresh_status()
        finally:
            st.session_state.motion_in_progress = False
            st.session_state.storage_confirmed = False

    st.divider()
    st.markdown("### 实时位姿")
    realtime_cols = st.columns([1, 1, 2])
    read_realtime = realtime_cols[0].button("读取实时状态", use_container_width=True, disabled=controls_disabled)
    auto_refresh = realtime_cols[1].checkbox("1 秒刷新", value=False, disabled=controls_disabled)
    realtime_cols[2].caption("TCP 单位 mm；关节和姿态单位为度。")
    if read_realtime or auto_refresh or st.session_state.get("realtime_state", {}).get("ok"):
        _render_realtime_state()
        if auto_refresh:
            time.sleep(1.0)
            st.rerun()

    with st.expander("最近响应与日志", expanded=False):
        st.code(status.get("last_response") or robot.last_dashboard_response or st.session_state.connection_test.get("message") or "暂无响应")
        if st.session_state.connection_test.get("ping_output"):
            st.caption("Ping 输出")
            st.code(st.session_state.connection_test.get("ping_output"))
        for item in st.session_state.get("robot_log", [])[:20]:
            st.text(item)


def _render_job_execution(config: Dict, root_dir: str) -> None:
    st.divider()
    st.markdown("### 数字轨迹执行")
    robot_type = st.selectbox("执行适配器", ["mock", "ur5"], index=0)
    trajectory_path = st.text_input("轨迹文件路径", value=st.session_state.get("latest_trajectory_path", ""))
    output_pin = int(config.get("output", {}).get("discharge_pin", 0))
    output_pin = st.number_input("出料数字输出 pin", min_value=0, max_value=7, value=output_pin, step=1)
    execute_confirmed = st.checkbox("我确认轨迹文件、工作空间和机械臂现场状态均允许执行")

    if st.button("执行轨迹文件", type="primary", disabled=not trajectory_path or not execute_confirmed or st.session_state.get("motion_in_progress", False)):
        source = Path(trajectory_path)
        if not source.exists():
            st.error("轨迹文件不存在")
            return
        trajectory = load_trajectory_file(source)
        adapter = MockRobotAdapter() if robot_type == "mock" else st.session_state.ur5_robot
        if robot_type == "mock":
            adapter.connect("mock")
        else:
            _sync_ip()

        st.session_state.motion_in_progress = True
        try:
            result = adapter.execute_trajectory(trajectory, output_pin=int(output_pin))
            if result.ok:
                st.success(result.message)
            else:
                st.error(result.message)
            _add_log(f"{robot_type} 执行：{result.message}")
        finally:
            st.session_state.motion_in_progress = False

    export_dir = Path(root_dir) / "data" / "exports"
    if export_dir.exists():
        latest = sorted(export_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        if latest:
            st.caption("最近数字文件")
            for item in latest:
                st.text(str(item))


def render(config: Dict, root_dir: str) -> None:
    _init_state(config)
    _render_ur5_control(config)
    _render_job_execution(config, root_dir)
