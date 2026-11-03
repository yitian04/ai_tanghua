from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, Mapping


@dataclass(frozen=True)
class URScriptExecutionProfile:
    output_pin: int = 0
    output_on_delay_ms: float = 0.0
    output_off_delay_ms: float = 0.0
    blend_radius_mm: float = 1.0
    max_speed_mm_s: float = 500.0
    acceleration_m_s2: float = 0.05

    def __post_init__(self):
        if type(self.output_pin) is not int or not 0<=self.output_pin<=7:raise ValueError('标准输出端口必须为 0–7。')
        for field in ('output_on_delay_ms','output_off_delay_ms','blend_radius_mm','max_speed_mm_s','acceleration_m_s2'):
            value=getattr(self,field)
            if not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:raise ValueError('执行参数必须为有限非负数。')
        if self.max_speed_mm_s<=0 or self.acceleration_m_s2<=0:raise ValueError('速度上限和加速度必须为正数。')

    def compile_options(self) -> Dict[str, Any]:
        return {
            "program_name": "Program",
            "output_on_delay_s": max(0.0, float(self.output_on_delay_ms)) / 1000.0,
            "output_off_delay_s": max(0.0, float(self.output_off_delay_ms)) / 1000.0,
            "blend_radius_m": max(0.0, float(self.blend_radius_mm)) / 1000.0,
            "max_speed_m_s": float(self.max_speed_mm_s) / 1000.0,
            "acceleration": max(0.001, float(self.acceleration_m_s2)),
        }

    def export_options(self) -> Dict[str, Any]:
        return {
            "program_name": "Program",
            "output_on_delay_ms": max(0.0, float(self.output_on_delay_ms)),
            "output_off_delay_ms": max(0.0, float(self.output_off_delay_ms)),
            "blend_radius_mm": max(0.0, float(self.blend_radius_mm)),
            "max_speed_m_s": float(self.max_speed_mm_s) / 1000.0,
            "acceleration": max(0.001, float(self.acceleration_m_s2)),
        }


def _float_from_mapping(data: Mapping[str, Any], key: str, fallback: float) -> float:
    value = data.get(key, fallback)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def execution_profile_from_config(config: dict) -> URScriptExecutionProfile:
    output = config.get("output", {}) if isinstance(config, dict) else {}
    execution = config.get("execution", {}) if isinstance(config, dict) else {}
    if not isinstance(output, dict):
        output = {}
    if not isinstance(execution, dict):
        execution = {}

    return URScriptExecutionProfile(
        output_pin=int(output.get("discharge_pin", execution.get("output_pin", 0))),
        output_on_delay_ms=_float_from_mapping(execution, "output_on_delay_ms", 0.0),
        output_off_delay_ms=_float_from_mapping(execution, "output_off_delay_ms", 0.0),
        blend_radius_mm=_float_from_mapping(execution, "blend_radius_mm", 1.0),
        max_speed_mm_s=_float_from_mapping(execution, "max_speed_mm_s", 500.0),
        acceleration_m_s2=_float_from_mapping(execution, "acceleration_m_s2", 0.05),
    )
