from __future__ import annotations

import json
import hashlib
import uuid
from dataclasses import asdict
from pathlib import Path

from apps.gui.parameter_ui import ui as st
from apps.gui.asset_library import file_input, image_input
import streamlit.components.v2 as components
from src.pipeline.trajectory_composition.editor import LayoutHistory

from apps.gui.views.file_naming import build_output_path
from apps.gui.views.planning_page import _planning_defaults
from src.pipeline.export.json_exporter import export_trajectory_json
from src.pipeline.trajectory_composition.composer import (
    Composition, Plane, compose, drawing_runs, import_trajectory, make_item,
    out_of_bounds, source_bounds, validate_plane,
)


@st.cache_resource
def _canvas_component(js: str):
    version = hashlib.sha256(js.encode()).hexdigest()[:12]
    return components.component(f"tanghua_layout_canvas_{version}", js=js)


def _changed():
    st.session_state["composition_revision"] = st.session_state.get("composition_revision", 0) + 1


def _history():
    if "composition_history" not in st.session_state:
        st.session_state["composition_history"] = LayoutHistory()
    return st.session_state["composition_history"]


def _record(doc):
    _history().record(doc, st.session_state.get("composition_selected"))


def _accept_canvas_edit():
    state = st.session_state.get("composition_canvas", {})
    event = state.get("edit")
    if not event:
        return
    if event.get("token") == st.session_state.get("composition_ack"):
        return
    st.session_state["composition_ack"] = event.get("token")
    # Relative/editor commands use the newest document. Only absolute transforms
    # need the same revision so a stale canvas cannot overwrite a newer edit.
    if event.get("action") != "transform" or event.get("revision") == st.session_state.get("composition_revision", 0):
        try:
            st.session_state["composition_selected"] = _history().perform(
                st.session_state["composition_document"], st.session_state.get("composition_selected"), event)
        except (ValueError, TypeError, KeyError) as exc:
            st.session_state["composition_notice"] = str(exc)
    _changed()


def _add(doc, content, name):
    trajectory = import_trajectory(content, name)
    item = make_item(trajectory, name, doc.plane)
    _record(doc)
    doc.items.append(item)
    st.session_state["composition_selected"] = item.id
    _changed()


def _import_objects(items, library):
    doc=st.session_state['composition_document']
    # Validate the complete selection before making one undoable batch edit.
    added=[make_item(import_trajectory(library.read(item),item['name']),item['name'],doc.plane) for item in items]
    if not added: return
    _record(doc)
    doc.items.extend(added)
    st.session_state['composition_selected']=added[-1].id
    _changed()


def _canvas_data(doc):
    items = []
    for item in doc.items:
        x0, y0, x1, y1 = source_bounds(item)
        cx, cy = (x0+x1)/2, (y0+y1)/2
        items.append({"id": item.id, "name": item.name, "width": x1-x0, "height": y1-y0,
                      "x_mm": item.x_mm, "y_mm": item.y_mm, "scale": item.scale,
                      "rotation_deg": item.rotation_deg,
                      "paths": [[[p.x_mm-cx, p.y_mm-cy] for p in run] for run in drawing_runs(item.trajectory)]})
    if "composition_editor_id" not in st.session_state:
        st.session_state["composition_editor_id"] = uuid.uuid4().hex
    history = _history()
    return {"width": doc.plane.width_mm, "height": doc.plane.height_mm, "items": items,
            "editor_id": st.session_state["composition_editor_id"],
            "ack": st.session_state.get("composition_ack"),
            "can_undo": bool(history.undo_stack), "can_redo": bool(history.redo_stack),
            "can_paste": history.clipboard is not None,
            "selected": st.session_state.get("composition_selected"),
            "revision": st.session_state.get("composition_revision", 0),
            "show_travel": st.session_state.get("composition_show_travel", False)}


def render(config: dict, root_dir: str) -> None:
    st.subheader("轨迹合成")
    st.caption("每个文件作为一个对象排布。画布单位为 mm，向右为 X 正向，向下为 Y 正向；列表顺序就是执行顺序。")
    if "composition_document" not in st.session_state:
        d = _planning_defaults(config)
        st.session_state["composition_document"] = Composition(Plane(
            width_mm=d["workspace_width_mm"], height_mm=d["workspace_height_mm"],
            center_x_mm=d["center_x_mm"], center_y_mm=d["center_y_mm"], draw_z_mm=d["draw_z_mm"],
            lift_mm=d["lift_z_mm"], travel_speed_mm_s=d["travel_speed_mm_s"],
            orientation=[d["tool_rx_deg"], d["tool_ry_deg"], d["tool_rz_deg"]]))
    doc = st.session_state["composition_document"]
    if not doc.items:
        from src.core.preferences import PreferenceStore
        remembered=PreferenceStore(root_dir).current('composition')
        for field,label in {'width_mm':'画布宽 mm','height_mm':'画布高 mm','center_x_mm':'机器人中心 X mm','center_y_mm':'机器人中心 Y mm','draw_z_mm':'绘制 Z mm','lift_mm':'抬笔高度 mm','travel_speed_mm_s':'空走速度 mm/s'}.items():
            if label in remembered:setattr(doc.plane,field,remembered[label])
        doc.plane.orientation=[remembered.get(label,value) for label,value in zip(('Rx deg','Ry deg','Rz deg'),doc.plane.orientation)]
    notice = st.session_state.pop("composition_notice", None)
    if notice:
        st.warning(notice)
    pending = st.session_state.pop("composition_pending_path", None)
    if pending:
        st.session_state["composition_candidate"] = pending
    # Keep the initial expansion stable while batches are imported or undone;
    # changing it with the object count can collapse controls mid-interaction.
    with st.expander("导入轨迹", expanded=True):
        file_input(root_dir, "composition_objects", "添加轨迹对象", {"trajectory"}, multiple=True, candidate=st.session_state.get("composition_candidate"),on_import=_import_objects)

    with st.expander("画布与共同绘制平面"):
        with st.container():
            a, b, c = st.columns(3)
            values = asdict(doc.plane)
            labels = {"width_mm":"画布宽 mm", "height_mm":"画布高 mm", "center_x_mm":"机器人中心 X mm", "center_y_mm":"机器人中心 Y mm", "draw_z_mm":"绘制 Z mm", "lift_mm":"抬笔高度 mm", "travel_speed_mm_s":"空走速度 mm/s"}
            for n, (key, label) in enumerate(labels.items()):
                values[key] = (a,b,c)[n%3].number_input(label, value=float(values[key]), key=f"composition_plane_{key}_{st.session_state.get('composition_revision',0)}")
            values["orientation"] = [col.number_input(label, value=float(v), key=f"composition_pose_{n}_{st.session_state.get('composition_revision',0)}") for n, (col,label,v) in enumerate(zip((a,b,c),("Rx deg","Ry deg","Rz deg"),doc.plane.orientation))]
            if st.button("应用画布与平面"):
                try:
                    plane = Plane(**values)
                    validate_plane(plane)
                    _record(doc)
                    doc.plane = plane
                    _changed()
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    controls, preview = st.columns([1, 2.3])
    with controls:
        if not doc.items:
            st.info("先导入图形或文字轨迹，再到右侧拖拽排布。")
        else:
            ids = [i.id for i in doc.items]
            if st.session_state.get("composition_selected") not in ids:
                st.session_state["composition_selected"] = ids[0]
            selected = st.session_state["composition_selected"]
            st.caption("对象属性 · 在右侧对象列表或画布中选择")
            item = next(i for i in doc.items if i.id == selected)
            index = doc.items.index(item)
            up, down = st.columns(2)
            if up.button("↑ 提前执行", disabled=index==0):
                _record(doc)
                doc.items[index-1],doc.items[index] = doc.items[index],doc.items[index-1]
                _changed(); st.rerun()
            if down.button("↓ 延后执行", disabled=index==len(doc.items)-1):
                _record(doc)
                doc.items[index+1],doc.items[index] = doc.items[index],doc.items[index+1]
                _changed(); st.rerun()
            x0,y0,x1,y1 = source_bounds(item)
            w,h = x1-x0,y1-y0
            rev = st.session_state.get("composition_revision",0)
            with st.form(f"composition_properties_{selected}_{rev}"):
                name = st.text_input("对象名称", item.name)
                x = st.number_input("中心 X mm", value=float(item.x_mm))
                y = st.number_input("中心 Y mm", value=float(item.y_mm))
                scale = st.number_input("等比缩放", min_value=.001, value=float(item.scale), format="%.4f")
                width = st.number_input("宽 mm", min_value=0.0, value=float(w*item.scale), disabled=w==0)
                height = st.number_input("高 mm", min_value=0.0, value=float(h*item.scale), disabled=h==0)
                angle = st.number_input("旋转 deg", value=float(item.rotation_deg))
                if st.form_submit_button("应用对象修改"):
                    # Exactly one sizing control can override scale in a single edit.
                    changed_w = abs(width-w*item.scale)>1e-8
                    changed_h = abs(height-h*item.scale)>1e-8
                    if changed_w and changed_h:
                        st.error("等比缩放时请只修改宽或高其中一项。")
                    else:
                        target = width/w if changed_w else (height/h if changed_h else scale)
                        if target<=0:
                            st.error("缩放后的大小必须大于零。")
                        else:
                            _record(doc)
                            item.name, item.x_mm, item.y_mm, item.scale, item.rotation_deg = name,x,y,target,angle
                            _changed(); st.rerun()
            a,b = st.columns(2)
            if a.button("居中"):
                _record(doc)
                item.x_mm,item.y_mm=doc.plane.width_mm/2,doc.plane.height_mm/2
                _changed(); st.rerun()
            if b.button("重置变换"):
                _record(doc)
                item.scale,item.rotation_deg=1.,0.
                item.x_mm,item.y_mm=doc.plane.width_mm/2,doc.plane.height_mm/2
                _changed(); st.rerun()
            if st.button("删除选中对象"):
                st.session_state["composition_selected"] = _history().perform(doc, selected, {"action":"delete"})
                _changed(); st.rerun()
    with preview:
        st.checkbox("显示重新生成的空走连接", key="composition_show_travel")
        canvas_js = (Path(__file__).parents[1] / "components" / "layout_canvas.js").read_text(encoding="utf-8")
        _canvas_component(canvas_js)(key="composition_canvas", data=_canvas_data(doc), on_edit_change=_accept_canvas_edit, height="content")
        outside = [i.name for i in doc.items if out_of_bounds(i, doc.plane)]
        if outside:
            st.error("超出画布：" + "、".join(outside) + "。请调整后再导出。")
        st.caption(f"画布 {doc.plane.width_mm:g} × {doc.plane.height_mm:g} mm · {len(doc.items)} 个对象；重叠允许。")
        output_name = st.text_input("合成文件名称", "糖画组合", key="composition_output_name")
        from apps.gui import workspace
        workspace.collect('composition') if workspace.root() else None
        current=workspace.draft('composition')
        if current and current.valid:
            for artifact in current.artifacts:
                if artifact.name.endswith('_trajectory.json'):
                    st.download_button("下载合成轨迹 JSON",artifact.payload,artifact.name)
            if st.button("前往数字文件导出"):
                workspace.request_navigation('数字文件',transfer=True)
                st.rerun()
