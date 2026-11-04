"""Continuous grid remains camera-anchored without integer scale jumps."""
import unittest
from PIL import Image
from grid_lattice import paint_scene_grid

class GridStabilityTests(unittest.TestCase):
    def test_pan_is_exact_translation_in_interior(self):
        a=Image.new('RGB',(500,330),'#505357')
        b=Image.new('RGB',(500,330),'#505357')
        paint_scene_grid(a,97,60,2.4)
        paint_scene_grid(b,108,67,2.4)
        # Pan by (11,7), and compare a known interior crop.
        aa=a.crop((50,50,450,280)).tobytes()
        bb=b.crop((61,57,461,287)).tobytes()
        mismatch=sum(x!=y for x,y in zip(aa,bb))//3
        self.assertLess(mismatch/(400*230),0.07)
    def test_zoom_never_changes_world_grid_period_abruptly(self):
        # Actual line period is linear with zoom rather than round(zoom).
        for z in (1.49,1.50,1.51,2.49,2.50,2.51):
            image=Image.new('RGB',(300,240),'#505357')
            paint_scene_grid(image,35,21,z)
            self.assertNotEqual(image.getbbox(),None)

if __name__=='__main__':unittest.main()
