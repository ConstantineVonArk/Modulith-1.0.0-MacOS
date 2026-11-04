"""Pixel-level regression checks for the optimized triangle rasterizer."""
import unittest
from volume_editor import Block, render_scene

class TriangleRaster3483(unittest.TestCase):
    def test_repeatable_angles(self):
        b=Block(w=72,d=42,h=55,rise=15)
        edits=[dict(block=0,wall='front',t0=.16,t1=.83,z0=6,z1=49,depth=-10,columns=4,column_style=2)]
        for angle in (0,45,135,225,315,345):
            with self.subTest(angle=angle):
                a=render_scene([b],angle=angle,wall_edits=edits)
                c=render_scene([b],angle=angle,wall_edits=edits)
                self.assertEqual(a.tobytes(),c.tobytes())
