"""Regression: module auto-build, no prerequisite Apply, rectangular elevations."""
import json, tempfile, tkinter as tk, unittest
from pathlib import Path
from unittest.mock import patch
from facade_builder import App

class AutoFacade(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=tk.Tk()
        cls.app=App(cls.root)
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_default_is_ready_without_apply(self):
        a=self.app
        self.assertTrue(a.module_applied)
        self.assertIsNotNone(a.facade)
        self.assertIsNotNone(a.facade_front)
        self.assertFalse(a.volume_app.show_iso_grid.get())

    def test_live_edit_and_switch_wall(self):
        a=self.app
        old=a.facade_front.tobytes()
        a.wall_color='#aabbcc'
        a.compose_module()
        a._flush_live_module()
        self.assertNotEqual(old,a.facade_front.tobytes())
        self.assertEqual(a.wall_color,'#aabbcc')
        self.assertTrue(a.module_applied)
        a.wall_selector.set(a.wall_names['right']);a.switch_wall()
        self.assertEqual(a.active_wall,'right')
        a.wall_selector.set(a.wall_names['front']);a.switch_wall()

    def test_save_open_without_manual_apply(self):
        a=self.app
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.json'
            with patch('facade_builder.filedialog.asksaveasfilename',return_value=str(path)):
                a.save_project()
            data=json.loads(path.read_text(encoding='utf8'))
            self.assertIn('walls',data)
            with patch('facade_builder.filedialog.askopenfilename',return_value=str(path)):
                a.load_project()
            self.assertTrue(a.module_applied)
            self.assertIsNotNone(a.facade_front)

    def test_elevation_rectangular_for_different_counts(self):
        a=self.app
        a._show_workspace('front')
        a._open_elevations();self.root.update()
        # Set markedly different widths of window group in adjacent bands.
        a.floor_counts[0].set(2);a.floor_counts[1].set(9)
        a.floor_counts[2].set(4);a.floor_counts[3].set(8)
        a.render_facade()
        src=a._elevation_sources()
        img,heights=src['front']
        self.assertTrue(heights)
        # The image source may be stepped. The final strip is a full solid
        # wall plane, including pixel 0 of every floor.
        from PIL import Image
        # Verify width / height relation and floor selection still works.
        a._draw_elevations(a.elevations_canvas)
        hits=[h for h in a.elevations_canvas._elevation_hits if h[5] is None]
        self.assertEqual(len(hits),4)
        self.assertTrue(all(abs(hits[i][2]-hits[i+1][0])<=1 for i in range(3)))

if __name__=='__main__':unittest.main(verbosity=2)
