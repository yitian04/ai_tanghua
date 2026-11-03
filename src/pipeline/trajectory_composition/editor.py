"""Session-local layout commands with bounded undo/redo history.

Snapshots copy layout attributes, sharing immutable source trajectories.
"""
from dataclasses import dataclass, field, replace
import math
import uuid

from .composer import Composition, LayoutItem


def snapshot(document, selected):
    return Composition(replace(document.plane, orientation=list(document.plane.orientation)),
                       [replace(item) for item in document.items]), selected


@dataclass
class LayoutHistory:
    undo_stack: list = field(default_factory=list)
    redo_stack: list = field(default_factory=list)
    clipboard: LayoutItem | None = None

    def record(self, document, selected):
        self.undo_stack.append(snapshot(document, selected))
        self.undo_stack[:] = self.undo_stack[-50:]
        self.redo_stack.clear()

    def perform(self, document, selected, event):
        action = event.get("action", "transform")
        item = next((i for i in document.items if i.id == event.get("id", selected)), None)
        if action == "select":
            return item.id if item else None
        if action in {"undo", "redo"}:
            source, target = ((self.undo_stack, self.redo_stack) if action == "undo"
                              else (self.redo_stack, self.undo_stack))
            if source:
                target.append(snapshot(document, selected))
                saved, selected = source.pop()
                document.plane, document.items = saved.plane, saved.items
            return selected
        if action == "copy":
            if item:
                self.clipboard = replace(item)
            return selected
        if action == "paste":
            if self.clipboard:
                self.record(document, selected)
                copy = replace(self.clipboard, id=uuid.uuid4().hex,
                               name=self.clipboard.name.removesuffix(" 副本") + " 副本",
                               x_mm=self.clipboard.x_mm+10, y_mm=self.clipboard.y_mm+10)
                document.items.append(copy)
                self.clipboard = replace(copy)
                return copy.id
            return selected
        if action == "reorder":
            order = event.get("order", [])
            lookup = {i.id: i for i in document.items}
            if len(order) != len(lookup) or set(order) != set(lookup):
                raise ValueError("对象列表已更新，请重新排序。")
            if order != [i.id for i in document.items]:
                self.record(document, selected)
                document.items = [lookup[id_] for id_ in order]
            return selected
        if not item:
            return selected
        if action == "delete":
            self.record(document, selected)
            index = document.items.index(item)
            document.items.remove(item)
            if selected == item.id:
                return document.items[min(index, len(document.items)-1)].id if document.items else None
            return selected
        if action == "move":
            values = (item.x_mm+float(event["dx"]), item.y_mm+float(event["dy"]), item.scale, item.rotation_deg)
        elif action == "transform":
            values = tuple(float(event.get(key, getattr(item, key))) for key in ("x_mm", "y_mm", "scale", "rotation_deg"))
        else:
            raise ValueError("不支持的布局操作。")
        if not all(math.isfinite(v) for v in values) or values[2] <= 0:
            raise ValueError("对象变换无效。")
        if values != (item.x_mm, item.y_mm, item.scale, item.rotation_deg):
            self.record(document, selected)
            item.x_mm, item.y_mm, item.scale, item.rotation_deg = values
        return item.id
