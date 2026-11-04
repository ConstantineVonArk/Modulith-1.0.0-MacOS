"""Rotation responsiveness and exact reuse of rendered camera views (needs Tk)."""
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from facade_builder import App
import volume_editor as editor

class AsyncRotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=tk.Tk()
        cls.app=App(cls.root)
        cls.v=cls.app.volume_app
        for i in range(80):
            cls.root.update()
            if getattr(cls.v,'_cache_key',None) is not None:
                break
            time.sleep(.015)
        assert cls.v._cache_key is not None

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def wait_for_angle(self,angle,limit=5):
        deadline=time.perf_counter()+limit
        while time.perf_counter()<deadline:
            self.root.update()
            if self.v._cache_key is not None and self.v._cache_key[0]==angle:
                return
            time.sleep(.010)
        self.fail(f'Angle {angle} not completed: {self.v.angle}, {self.v._cache_key[0]}')

    def test_worker_keeps_main_thread_responsive_and_matches_exact_pixels(self):
        v=self.v
        original=editor.render_scene
        calls=[]
        def slower(*args,**kwargs):
            calls.append(kwargs.get('angle'))
            time.sleep(.17)
            return original(*args,**kwargs)
        with patch.object(editor,'render_scene',side_effect=slower):
            v.rotate(15)
            self.root.update()
            time.sleep(.030)
            self.root.update()
            self.assertEqual(v.angle,15)
            self.assertNotEqual(v._cache_key[0],15)
            # Fast clicks must not enqueue all intervening angles.
            v.rotate(15)
            v.rotate(15)
            v.rotate(15)
            self.wait_for_angle(60)
            self.assertEqual(v._native_scene.tobytes(),original(v.blocks,60,
                cast_shadow=v.cast_shadow.get(),facade_texture=v.facade_texture,
                facade_source=v.facade_source,facade_filter=v.facade_filter,
                facade_front=v.facade_front,**v.roof_render_options(),
                roof_accessories=v.roof_accessories,
                accessory_wall_color=v.accessory_wall_color,wall_edits=v.wall_edits,
                wall_facades=v.wall_facades).tobytes())
            self.assertLessEqual(len(calls),3)
        # Returning to a cached view must not call render_scene again.
        v.rotate(-45)
        self.wait_for_angle(15)
        self.assertLessEqual(len(v._angle_frames),v._angle_frames_limit)

if __name__=='__main__':unittest.main()
