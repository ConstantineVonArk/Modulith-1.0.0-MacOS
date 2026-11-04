"""Regression tests for the revised column atlas and reverse-lit Ionic capital.
Run with `python3 test_column_projection_335.py` from the project directory.
"""
import unittest
from PIL import Image
import volume_editor as ve


class ColumnProjection335(unittest.TestCase):
    def test_atlas_roles_and_ionic_foot(self):
        # Low frame 2 is now upper capital art, not a circular foot.
        source_foot = ve._column_sheet_frame('low',3)
        source_cap = ve._column_sheet_frame('low',2)
        self.assertIsNotNone(source_cap)
        self.assertIsNotNone(source_foot)
        self.assertNotEqual(source_cap.tobytes(), source_foot.tobytes())
        self.assertEqual(ve.column_part_sprite(2,'low').tobytes(),source_foot.tobytes())
        for style,cell in ((1,0),(3,4)):
            with self.subTest(style=style):
                self.assertEqual(ve.column_part_sprite(style,'low').tobytes(),
                                 ve._column_sheet_frame('low',cell).tobytes())
        for style in (1,2,3):
            self.assertEqual(ve.column_part_sprite(style,'mid',diagonal=False).tobytes(),
                             ve.column_part_sprite(style,'mid',diagonal=True).tobytes())

    def test_ionic_iso_reverse_has_hand_painted_lighting(self):
        alternate=ve._column_sheet_frame('low',2)
        for angle in (90,270):
            with self.subTest(angle=angle):
                mode,mirror,raw=ve.capital_angle_mapping(angle)
                self.assertEqual((mode,mirror),('iso',True))
                actual=ve.column_capital_source(2,mode,mirror)
                self.assertEqual(actual.tobytes(),alternate.tobytes())
                projected,_,_=ve.projected_column_capital(2,mode,mirror=mirror,raw=raw)
                self.assertEqual(projected.tobytes(),alternate.tobytes())
        self.assertEqual(ve.column_capital_source(2,'iso').tobytes(),
                         ve._column_sheet_frame('up',2).tobytes())
        # Other two styles retain the previous mirrored ISO behavior.
        for style in (1,3):
            src=ve._column_sheet_frame('up',(style-1)*2)
            actual=ve.column_capital_source(style,'iso',mirror=True)
            self.assertEqual(actual.tobytes(),src.transpose(Image.FLIP_LEFT_RIGHT).tobytes())

    def test_profiles_never_mirror_in_any_profile_sector(self):
        for style in (1,2,3):
            native=ve._column_sheet_frame('mid',(style-1)*2+1)
            self.assertEqual(ve.column_capital_source(style,'profile',mirror=True).tobytes(),
                             native.tobytes())
            for angle in (30,45,60,210,225,240):
                with self.subTest(style=style,angle=angle):
                    mode,mirror,raw=ve.capital_angle_mapping(angle)
                    self.assertEqual(mode,'profile')
                    self.assertFalse(mirror)
                    if angle in (45,225):
                        self.assertTrue(raw)
                        img,_,_=ve.projected_column_capital(style,mode,raw=raw)
                        self.assertEqual(img.tobytes(),native.tobytes())

    def test_all_styles_all_rotations_render(self):
        body=ve.Block(w=64,d=24,h=70,rise=12)
        for style in (1,2,3):
            niche=dict(block=0,wall='front',t0=.15,t1=.85,z0=10,z1=55,
                       depth=-9,columns=3,column_style=style)
            for angle in range(0,360,15):
                with self.subTest(style=style,angle=angle):
                    rendered=ve.render_scene([body],angle=angle,wall_edits=[niche])
                    self.assertGreater(rendered.width,0)
                    self.assertGreater(rendered.height,0)

if __name__ == '__main__':
    unittest.main(verbosity=2)
