"""Regression guard: preview mask cache must not alter canonical renderer."""
import unittest
from volume_editor import Block, render_scene

class PreviewCacheTests(unittest.TestCase):
    def test_deterministic_render(self):
        block=Block(w=48,d=32,h=36,rise=12)
        for a in (0,45,315,345):
            x=render_scene([block],angle=a)
            y=render_scene([block],angle=a)
            self.assertEqual(x.tobytes(),y.tobytes())

if __name__=='__main__':unittest.main()
