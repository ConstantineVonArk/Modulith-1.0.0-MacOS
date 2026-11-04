"""Pixel-perfect check for viewport-only NEAREST sampling in version 3.48.20."""
import random
import unittest
from PIL import Image, ImageChops
from viewport_sampler import np, sample, visible_box


class VisiblePreviewTests(unittest.TestCase):
    @unittest.skipIf(np is None, 'NumPy optional acceleration unavailable')
    def test_random_rectangles_are_pixel_identical_to_pillow(self):
        rng = random.Random(34820)
        for _ in range(140):
            w = rng.randint(6, 147)
            h = rng.randint(6, 105)
            dw = rng.randint(16, 395)
            dh = rng.randint(16, 310)
            rgb = Image.frombytes('RGB',(w,h),rng.randbytes(w*h*3))
            obj = Image.frombytes('L',(w,h),rng.randbytes(w*h))
            shadow = Image.frombytes('L',(w,h),rng.randbytes(w*h))
            cw,ch = rng.randint(40,265),rng.randint(40,205)
            left,top = rng.randint(-dw,dw),rng.randint(-dh,dh)
            clip = visible_box((dw,dh),(cw,ch),left,top)
            if clip is None:continue
            result = sample(rgb,(obj,shadow),(dw,dh),clip)
            for original,actual in zip((rgb,obj,shadow),result):
                expected=original.resize((dw,dh),Image.Resampling.NEAREST).crop(clip)
                self.assertIsNone(ImageChops.difference(expected,actual).getbbox())

    def test_offscreen(self):
        self.assertIsNone(visible_box((100,100),(300,200),-900,0))


if __name__=='__main__':unittest.main()
