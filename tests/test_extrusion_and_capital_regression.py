"""Regression checks for volume extrusion with sprite columns (v3.31).

Run from the project directory:
    python3 test_extrusion_and_capital_regression.py

No GUI or display server is required.
"""
import unittest
from PIL import Image, ImageChops
import volume_editor as ve


class ExtrusionAndCapitalRegression(unittest.TestCase):
    def setUp(self):
        self.block = ve.Block(x=0, y=0, w=64, d=24, h=70, rise=12)
        self.niche = {
            'block':0, 'wall':'front', 't0':.2, 't1':.8,
            'z0':10., 'z1':55., 'depth':-8., 'columns':3, 'column_style':1,
        }
        self.protrusion = {
            'block':0, 'wall':'front', 't0':.15, 't1':.4,
            'z0':10., 'z1':25., 'depth':4., 'columns':0, 'column_style':1,
        }

    def test_capital_profiles_and_unchanged_shaft(self):
        for style in (1,2,3):
            shaft=ve.column_part_sprite(style, 'mid', diagonal=True)
            real_shaft=ve.column_part_sprite(style, 'mid', diagonal=False)
            self.assertEqual(shaft.tobytes(),real_shaft.tobytes())
            for mode in ('iso','front','profile'):
                with self.subTest(style=style,mode=mode):
                    sprite,dx,seam=ve.projected_column_capital(style,mode=mode,rise_px=4)
                    self.assertIsNotNone(sprite)
                    self.assertGreater(sprite.getbbox()[2],sprite.getbbox()[0])
                    self.assertLess(seam,sprite.height)
            profile=ve.column_capital_source(style,mode='profile')
            mirror=ve.column_capital_source(style,mode='profile',mirror=True)
            self.assertEqual(mirror.tobytes(),profile.tobytes())

    def test_extrusion_both_with_and_without_niche(self):
        for edits in ([self.protrusion],[self.niche],[self.niche,self.protrusion]):
            for angle in (0,45,90,180,225,270,285,315,345):
                with self.subTest(angle=angle,edits=len(edits)):
                    pic=ve.render_scene([self.block],angle=angle,
                                        wall_edits=edits,cast_shadow=False)
                    self.assertGreater(pic.width,0)
                    self.assertGreater(pic.height,0)

    def test_positive_extrusion_is_visible(self):
        # Check the final rendered pixels, not merely the edit list.
        base=ve.render_scene([self.block],angle=315,wall_edits=[self.niche])
        altered=ve.render_scene([self.block],angle=315,
                                wall_edits=[self.niche,self.protrusion])
        self.assertEqual(base.size,altered.size)
        self.assertIsNotNone(ImageChops.difference(base,altered).getbbox())


if __name__=='__main__':
    unittest.main(verbosity=2)
