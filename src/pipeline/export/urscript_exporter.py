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
    import base64,json,secrets
    from src.robot.ur5.guarded_script import build_guarded_script
    config=compile_options.pop('path_config',None)
    if config is None:raise ValueError('机器人程序导出需要已验证的示教路径。')
    if output_pin!=config['output_pin']:raise ValueError('导出端口必须与已验证路径相同。')
    options=dict(compile_options)
    options.update(output_on_delay_s=float(output_on_delay_ms)/1000,
                   output_off_delay_s=float(output_off_delay_ms)/1000,blend_radius_m=float(blend_radius_mm)/1000)
    script=build_guarded_script(trajectory,config,secrets.randbelow(2147483645)+1,options)
    manifest={'trajectory':trajectory.to_dict(),'path_config':config,'options':options}
    encoded=base64.b64encode(json.dumps(manifest,allow_nan=False).encode()).decode()
    header=['# tanghua_control_v1']+['# data: '+encoded[n:n+100] for n in range(0,len(encoded),100)]+['# end_tanghua_control']
    script='\n'.join(header)+'\n'+script
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".urp":
        output.write_text(_build_urp_xml(script, output.stem, template_path), encoding="utf-8")
    else:
        output.write_text(script, encoding="utf-8")
    return output


def load_controlled_program(path):
    """Only our generated, embedded manifest is accepted; never eval URScript."""
    import base64,json
    text=Path(path).read_text(encoding='utf-8-sig')
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise ValueError('不支持此程序文件。')
    if Path(path).suffix.lower()=='.urp':text=ET.fromstring(text).findtext('.//cachedContents','')
    lines=text.splitlines()
    if not lines or lines[0]!='# tanghua_control_v1':raise ValueError('仅支持本项目生成的受监控机器人程序。')
    end=lines.index('# end_tanghua_control')
    if not all(line.startswith('# data: ') for line in lines[1:end]):raise ValueError('程序清单损坏。')
    data=json.loads(base64.b64decode(''.join(line[8:] for line in lines[1:end]),validate=True))
    return Trajectory.from_dict(data['trajectory']),data['path_config'],data['options']


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
