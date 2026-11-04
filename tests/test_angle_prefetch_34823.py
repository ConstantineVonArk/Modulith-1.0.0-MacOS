"""Regression: idle pre-rendering makes adjacent angles immediately available."""
import time
import tkinter as tk
import unittest
from facade_builder import App

class AnglePrefetchTests(unittest.TestCase):
    def test_neighbours_prefetched_without_changing_view(self):
        root=tk.Tk()
        try:
            app=App(root);v=app.volume_app
            deadline=time.monotonic()+8
            while time.monotonic()<deadline and getattr(v,'_cache_key',None) is None:
                root.update();time.sleep(.01)
            self.assertIsNotNone(v._cache_key)
            original=v.angle
            target=(original+15)%360
            deadline=time.monotonic()+9
            while time.monotonic()<deadline and not any(k[0]==target for k in v._angle_frames):
                root.update();time.sleep(.015)
            self.assertTrue(any(k[0]==target for k in v._angle_frames))
            self.assertEqual(v.angle,original)
            self.assertEqual(v._cache_key[0],original)
            v.rotate(15)
            deadline=time.monotonic()+1
            while time.monotonic()<deadline and v._cache_key[0]!=target:
                root.update();time.sleep(.008)
            self.assertEqual(v._cache_key[0],target)
            self.assertFalse(v._rotation_waiting)
        finally:
            root.destroy()

if __name__=='__main__':unittest.main()
