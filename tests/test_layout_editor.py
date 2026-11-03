import unittest

from src.core.models import Trajectory, TrajectoryPoint
from src.pipeline.trajectory_composition.composer import Composition, make_item
from src.pipeline.trajectory_composition.editor import LayoutHistory


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.doc = Composition()
        self.item = make_item(Trajectory([TrajectoryPoint(0,0,1,10,True), TrajectoryPoint(20,10,1,10,True)]), "文字", self.doc.plane)
        self.doc.items.append(self.item)
        self.history = LayoutHistory()
        self.selected = self.item.id

    def act(self, action, **values):
        self.selected = self.history.perform(self.doc, self.selected, {"action":action, **values})

    def test_transform_undo_redo_and_new_branch(self):
        self.act("transform", rotation_deg=90, scale=2)
        self.act("move", dx=10, dy=5)
        self.act("undo")
        self.assertEqual(self.doc.items[0].x_mm,150)
        self.assertEqual(self.doc.items[0].rotation_deg,90)
        self.act("undo")
        self.assertEqual(self.doc.items[0].scale,1)
        self.act("redo")
        self.assertEqual(self.doc.items[0].scale,2)
        self.act("move",dx=1,dy=0)
        self.assertFalse(self.history.redo_stack)
        self.assertEqual(self.item.trajectory.points[0].x_mm,0)

    def test_copy_delete_paste_and_selection(self):
        self.act("copy")
        self.act("delete")
        self.assertIsNone(self.selected)
        self.act("paste")
        copy = self.doc.items[0]
        self.assertNotEqual(copy.id,self.item.id)
        self.assertEqual(copy.x_mm,self.item.x_mm+10)
        self.assertIs(copy.trajectory,self.item.trajectory)
        self.act("undo")
        self.assertEqual(len(self.doc.items),0)
        self.act("undo")
        self.assertEqual(self.selected,self.item.id)
        self.act("paste")
        self.assertEqual(self.doc.items[-1].x_mm,self.item.x_mm+20)

    def test_reorder_and_limit(self):
        self.act("copy");self.act("paste")
        order=[i.id for i in self.doc.items]
        self.act("reorder",order=order[::-1])
        self.assertEqual([i.id for i in self.doc.items],order[::-1])
        self.act("undo")
        self.assertEqual([i.id for i in self.doc.items],order)
        with self.assertRaises(ValueError):self.act("reorder",order=[order[0],order[0]])
        with self.assertRaises(ValueError):self.act("transform",rotation_deg=float('nan'))
        for _ in range(60):self.act("move",dx=1,dy=0)
        self.assertEqual(len(self.history.undo_stack),50)


if __name__ == "__main__":unittest.main()
