"""UI smoke tests for real FRONT facade elevations, selection and state isolation.
Run with: xvfb-run -a python -m unittest test_elevations_34810 -v
"""
import unittest
import tkinter as tk
from facade_builder import App


class Elevations34810(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=tk.Tk()
        cls.app=App(cls.root)
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_real_images_and_side_width(self):
        app=self.app
        app.apply_module()
        images=app._elevation_sources()
        self.assertEqual(set(images),set(app.wall_names))
        for wall,(image,heights) in images.items():
            self.assertEqual(image.mode,'RGBA')
            self.assertGreater(image.width,10)
            self.assertGreater(sum(heights),0)
            self.assertEqual(image.height,sum(heights))
            if app.wall_configs[wall]['facade_front'] is not None:
                self.assertEqual(image.size,app.wall_configs[wall]['facade_front'].size)
        # A densely populated side may grow to the same pixel width as the
        # front; its nominal building span must remain independent.
        self.assertNotEqual(app.pair_widths['front'],app.pair_widths['side'])

    def test_popout_and_tray_select_same_wall(self):
        app=self.app
        app._show_workspace('front')
        app._toggle_module_section('elevation',True)
        app._open_elevations()
        self.root.update()
        self.assertEqual(len(app.elevations_canvas._elevation_refs),4)
        self.assertEqual(len(app.elevations_tray_canvas._elevation_refs),4)
        # Pick the left wall in the big elevation; both views update.
        hit=next(h for h in app.elevations_canvas._elevation_hits if h[4]=='left' and h[5] is None)
        class Event: pass
        event=Event();event.x=hit[0]+8;event.y=hit[1]+8
        app._elevation_click(event,app.elevations_canvas)
        self.root.update()
        self.assertEqual(app.active_wall,'left')
        self.assertEqual(app.wall_selector.get(),app.wall_names['left'])
        # Pick a specific upper-floor band from the actual wall raster.
        floor_hit=next(h for h in app.elevations_canvas._elevation_hits if h[4]=='left' and h[5]==3)
        event.x=(floor_hit[0]+floor_hit[2])/2
        event.y=(floor_hit[1]+floor_hit[3])/2
        app._elevation_click(event,app.elevations_canvas)
        self.assertEqual(app.active_type,3)
        # Pick the front again from the narrow left-hand tray.
        hit=next(h for h in app.elevations_tray_canvas._elevation_hits if h[4]=='front' and h[5] is None)
        event.x=hit[0]+8;event.y=hit[1]+8
        app._elevation_click(event,app.elevations_tray_canvas)
        self.root.update()
        self.assertEqual(app.active_wall,'front')
        app._hide_module_popup('elevations')

    def test_view_controls(self):
        app=self.app
        app._show_workspace('iso')
        app.module_preview_view.set('FRONT')
        app._preview_view_selected()
        self.root.update()
        self.assertEqual(app.module_view.get(),'FRONT')
        app.module_preview_wall.set(app.wall_names['right'])
        app.switch_wall()
        self.assertEqual(app.active_wall,'right')

if __name__=='__main__':unittest.main()
