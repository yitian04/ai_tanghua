from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from src.core.models import Trajectory
from src.robot.ur5.urscript_builder import compile_urscript

_DEFAULT_TEMPLATE = Path(__file__).resolve().parents[2] / "robot" / "ur5" / "templates" / "example.urp"


def export_trajectory_urscript(
    trajectory: Trajectory,
    path: str | Path,
    output_pin: int = 0,
    output_on_delay_ms: float = 0.0,
    output_off_delay_ms: float = 0.0,
    blend_radius_mm: float = 1.0,
    template_path: str | Path | None = None,
    **compile_options,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    script = compile_urscript(
        trajectory,
        output_pin=int(output_pin),
        output_on_delay_s=max(0.0, float(output_on_delay_ms)) / 1000.0,
        output_off_delay_s=max(0.0, float(output_off_delay_ms)) / 1000.0,
        blend_radius_m=max(0.0, float(blend_radius_mm)) / 1000.0,
        program_name=str(compile_options.pop("program_name", "Program")),
        **compile_options,
    )
    if output.suffix.lower() == ".urp":
        output.write_text(_build_urp_xml(script, output.stem, template_path), encoding="utf-8")
    else:
        output.write_text(script, encoding="utf-8")
    return output


def _build_urp_xml(script: str, program_name: str, template_path: str | Path | None = None) -> str:
    root = _load_template_root(template_path)
    root.set("name", program_name)

    cached = root.find(".//cachedContents")
    if cached is None:
        script_node = root.find(".//Script")
        if script_node is None:
            children = root.find("./children/MainProgram/children")
            if children is None:
                children = ET.SubElement(ET.SubElement(ET.SubElement(root, "children"), "MainProgram"), "children")
            script_node = ET.SubElement(children, "Script", {"type": "File"})
        cached = ET.SubElement(script_node, "cachedContents")
    cached.text = script

    file_node = root.find(".//Script/file")
    if file_node is None:
        script_node = root.find(".//Script")
        file_node = ET.SubElement(script_node, "file") if script_node is not None else None
    if file_node is not None:
        file_node.text = f"{program_name}.script"

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", short_empty_elements=False)


def _load_template_root(template_path: str | Path | None) -> ET.Element:
    candidates = []
    if template_path:
        candidates.append(Path(template_path))
    candidates.append(_DEFAULT_TEMPLATE)

    for candidate in candidates:
        if candidate.exists():
            return ET.parse(candidate).getroot()

    return _build_fallback_root()


def _build_fallback_root() -> ET.Element:
    root = ET.Element(
        "URProgram",
        {
            "name": "tanghua_template",
            "installation": "default",
            "installationRelativePath": "../../programs/default",
            "directory": "/programs/usbdisk",
            "createdIn": "3.15.6.0",
            "lastSavedIn": "3.15.8.106339",
        },
    )
    kinematics = ET.SubElement(root, "kinematics", {"status": "LINEARIZED", "validChecksum": "false"})
    for tag, value in {
        "deltaTheta": "0, 0, 0, 0, 0, 0",
        "a": "0, -0.425, -0.3922, 0, 0, 0",
        "d": "0.1625, 0, 0, 0.1333, 0.0997, 0.0996",
        "alpha": "1.5707963267948966, 0, 0, 1.5707963267948966, -1.5707963267948966, 0",
        "jointChecksum": "0, 0, 0, 0, 0, 0",
    }.items():
        ET.SubElement(kinematics, tag, {"value": value})
    children = ET.SubElement(root, "children")
    main = ET.SubElement(children, "MainProgram", {"runOnlyOnce": "true", "InitVariablesNode": "false"})
    main_children = ET.SubElement(main, "children")
    script = ET.SubElement(main_children, "Script", {"type": "File"})
    ET.SubElement(script, "cachedContents")
    ET.SubElement(script, "file")
    return root
