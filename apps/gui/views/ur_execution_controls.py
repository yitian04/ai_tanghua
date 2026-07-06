from __future__ import annotations

from pathlib import Path

import streamlit as st
import yaml

from src.robot.ur5.execution_profile import URScriptExecutionProfile, execution_profile_from_config


_PROFILE_KEYS = {
    "output_on_delay_ms": "urscript_output_on_delay_ms",
    "output_off_delay_ms": "urscript_output_off_delay_ms",
    "blend_radius_mm": "urscript_blend_radius_mm",
    "max_speed_mm_s": "urscript_max_speed_mm_s",
    "acceleration_m_s2": "urscript_acceleration_m_s2",
}


def render_urscript_execution_profile(config: dict) -> URScriptExecutionProfile:
    defaults = execution_profile_from_config(config)
    st.caption("UR5/URScript 导出参数：影响 URP 和直接发送 URScript，不写入通用 trajectory.json。")
    col_a, col_b, col_c = st.columns(3)
    output_on_delay_ms = col_a.number_input(
        "DO 打开延时 ms",
        min_value=0.0,
        value=float(st.session_state.get(_PROFILE_KEYS["output_on_delay_ms"], defaults.output_on_delay_ms)),
        step=10.0,
        key=_PROFILE_KEYS["output_on_delay_ms"],
    )
    output_off_delay_ms = col_b.number_input(
        "DO 关闭延时 ms",
        min_value=0.0,
        value=float(st.session_state.get(_PROFILE_KEYS["output_off_delay_ms"], defaults.output_off_delay_ms)),
        step=10.0,
        key=_PROFILE_KEYS["output_off_delay_ms"],
    )
    blend_radius_mm = col_c.number_input(
        "blend mm",
        min_value=0.0,
        value=float(st.session_state.get(_PROFILE_KEYS["blend_radius_mm"], defaults.blend_radius_mm)),
        step=0.1,
        key=_PROFILE_KEYS["blend_radius_mm"],
    )

    col_d, col_e = st.columns(2)
    max_speed_mm_s = col_d.number_input(
        "URScript最高速度 mm/s",
        min_value=1.0,
        value=float(st.session_state.get(_PROFILE_KEYS["max_speed_mm_s"], defaults.max_speed_mm_s)),
        step=50.0,
        key=_PROFILE_KEYS["max_speed_mm_s"],
    )
    acceleration_m_s2 = col_e.number_input(
        "URScript加速度 m/s²",
        min_value=0.001,
        value=float(st.session_state.get(_PROFILE_KEYS["acceleration_m_s2"], defaults.acceleration_m_s2)),
        step=0.01,
        format="%.3f",
        key=_PROFILE_KEYS["acceleration_m_s2"],
    )

    return URScriptExecutionProfile(
        output_pin=defaults.output_pin,
        output_on_delay_ms=float(output_on_delay_ms),
        output_off_delay_ms=float(output_off_delay_ms),
        blend_radius_mm=float(blend_radius_mm),
        max_speed_mm_s=float(max_speed_mm_s),
        acceleration_m_s2=float(acceleration_m_s2),
    )


def save_urscript_execution_defaults(root_dir: str, profile: URScriptExecutionProfile) -> Path:
    config_path = Path(root_dir) / "config" / "settings.yaml"
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        config = {}
    if not isinstance(config, dict):
        config = {}

    execution = config.get("execution")
    if not isinstance(execution, dict):
        execution = {}
    execution.update(
        {
            "output_on_delay_ms": float(profile.output_on_delay_ms),
            "output_off_delay_ms": float(profile.output_off_delay_ms),
            "blend_radius_mm": float(profile.blend_radius_mm),
            "max_speed_mm_s": float(profile.max_speed_mm_s),
            "acceleration_m_s2": float(profile.acceleration_m_s2),
        }
    )
    config["execution"] = execution
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return config_path


def execution_profile_caption(profile: URScriptExecutionProfile) -> str:
    return (
        "UR5 执行参数："
        f"DO{profile.output_pin}, 打开延时 {profile.output_on_delay_ms:g} ms, "
        f"关闭延时 {profile.output_off_delay_ms:g} ms, blend {profile.blend_radius_mm:g} mm, "
        f"最高速度 {profile.max_speed_mm_s:g} mm/s, 加速度 {profile.acceleration_m_s2:g} m/s²。"
    )
