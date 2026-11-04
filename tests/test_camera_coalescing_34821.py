"""3.48.21 regressions: input coalescing, immediate drag feedback, and stable preview."""
import tkinter as tk
import unittest
from types import SimpleNamespace
from facade_builder import App


class CameraCoalescingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.app = App(cls.root)
        cls.root.update_idletasks()
        cls.root.update()
        cls.editor = cls.app.volume_app
        cls.editor.refresh()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_fast_camera_events_share_a_single_pending_draw(self):
        v = self.editor
        v.refresh()
        v.change_zoom(.08, (160, 130))
        first = v.after_id
        self.assertIsNotNone(first)
        for _ in range(30):
            v.change_zoom(.01, (160, 130))
            self.assertEqual(first, v.after_id,
                             'Every zoom event must reuse the pending draw')
        v.root.after_cancel(v.after_id)
        v.after_id = None
        v.refresh()
        self.assertEqual(v.canvas.coords(v._canvas_render_id), [0., 0.])

    def test_drag_moves_bitmap_immediately_then_renders_exact_position(self):
        v = self.editor
        v.refresh()
        before = tuple(v.preview_pan)
        v.pan_start(SimpleNamespace(x=50, y=60))
        v.pan_motion(SimpleNamespace(x=68, y=49))
        self.assertEqual(v.canvas.coords(v._canvas_render_id), [18., -11.])
        self.assertAlmostEqual(v.preview_pan[0], before[0]+18)
        self.assertAlmostEqual(v.preview_pan[1], before[1]-11)
        if v.after_id is not None:
            v.root.after_cancel(v.after_id)
            v.after_id=None
        v.refresh()
        self.assertEqual(v.canvas.coords(v._canvas_render_id), [0., 0.])
        self.assertEqual(tuple(v._display_preview_pan),tuple(v.preview_pan))

    def test_scene_and_roof_plan_reuse(self):
        v=self.editor
        v.refresh()
        native=v._native_scene
        roof_items=tuple(v.context_canvas.find_all())
        v.change_zoom(.06, (150,110))
        if v.after_id is not None:
            v.root.after_cancel(v.after_id)
            v.after_id=None
        v.refresh()
        self.assertIs(v._native_scene,native)
        self.assertEqual(roof_items,tuple(v.context_canvas.find_all()))

if __name__=='__main__': unittest.main()
