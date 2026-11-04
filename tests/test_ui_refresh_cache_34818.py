"""Regression checks for 3.48.18 preview caching (requires Tk display)."""
import unittest
import tkinter as tk
from facade_builder import App


class PreviewRefreshCache34818(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=tk.Tk()
        cls.app=App(cls.root)
        cls.root.update_idletasks()
        cls.root.update()
        cls.editor=cls.app.volume_app

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_unchanged_scene_keeps_photo_and_roof_plan(self):
        editor=self.editor
        editor.refresh()
        initial_photo=editor.photo
        initial_canvas_id=editor._canvas_render_id
        roof_items=tuple(editor.context_canvas.find_all())
        editor.refresh()
        self.assertIs(editor.photo,initial_photo)
        self.assertEqual(editor._canvas_render_id,initial_canvas_id)
        self.assertEqual(tuple(editor.context_canvas.find_all()),roof_items)

    def test_pan_recomposes_without_rebuilding_roof_plan(self):
        editor=self.editor
        editor.refresh()
        prev_photo=editor.photo
        roof_items=tuple(editor.context_canvas.find_all())
        editor.preview_pan[0]+=11
        editor.refresh()
        self.assertIsNot(editor.photo,prev_photo)
        self.assertEqual(tuple(editor.context_canvas.find_all()),roof_items)


if __name__=='__main__':
    unittest.main()
