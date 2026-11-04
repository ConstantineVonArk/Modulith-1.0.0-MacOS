"""Smoke tests for continuous strip, physical ratios, click-through and persistent palettes."""
import tkinter as tk
import unittest
from facade_builder import App

class ContinuousElevationStrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.app = App(cls.root)
        cls.app._show_workspace('front')
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_one_scale_and_physical_widths(self):
        app = self.app
        app._open_elevations()
        self.root.update()
        app._draw_elevations(app.elevations_canvas)
        layout = app.elevations_canvas._elevation_layout
        self.assertEqual(len(app.elevations_canvas._elevation_refs), 4)
        dims = layout['widths']
        self.assertEqual(dims['front'],dims['back'])
        self.assertEqual(dims['left'],dims['right'])
        b = app.volume_app.blocks[app.volume_app.active]
        self.assertAlmostEqual(dims['front']/dims['right'], b.w/b.d, delta=0.03)
        # The four wall hit regions must be adjacent, not card separated.
        hit = [h for h in app.elevations_canvas._elevation_hits if h[5] is None]
        self.assertEqual([h[4] for h in hit],['front','right','back','left'])
        for previous,nxt in zip(hit,hit[1:]):
            self.assertAlmostEqual(previous[2],nxt[0],delta=1.5)
            self.assertAlmostEqual(previous[3],nxt[3],delta=0.01)

    def test_selected_wall_and_floor(self):
        app=self.app
        class Event:pass
        floor=next(h for h in app.elevations_canvas._elevation_hits if h[4]=='right' and h[5]==3)
        event=Event()
        event.x=(floor[0]+floor[2])/2
        event.y=(floor[1]+floor[3])/2
        app._elevation_click(event,app.elevations_canvas)
        self.assertEqual(app.active_wall,'right')
        self.assertEqual(app.active_type,3)
        self.assertEqual(app.preview_floor_choice.get(),app.type_names[3])

    def test_palette_stays_above_main_window(self):
        app=self.app
        app._open_module_popup('rust')
        app._open_elevations()
        app.volume_app._toolbar_body_size()
        app.volume_app._toolbar_roof_settings()
        self.root.update()
        for win in [app._module_popup_windows['rust'],app._module_popup_windows['elevations'],
                    app.volume_app.geometry_window,app.volume_app.roof_window]:
            self.assertEqual(int(win.attributes('-topmost')),1)
        self.assertFalse(app.preview_floor_choice is None)

if __name__ == '__main__':unittest.main()
