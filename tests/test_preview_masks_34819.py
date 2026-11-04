"""Verify mask-before-resize == old resize-before-mask for RGB/RGBA scenes."""
import unittest
import random
from PIL import Image, ImageChops
from preview_masks import native_masks, scaled_masks

BG = (83,86,90)
SHADOW = (70,68,74)

def old_masks(im, size, shadows):
    src=im.resize(size,Image.Resampling.NEAREST).convert('RGB')
    nonbg=ImageChops.difference(src,Image.new('RGB',size,BG)).convert('L')
    nonbg=nonbg.point(lambda v:255 if v else 0)
    sh=None
    if shadows:
        diff=ImageChops.difference(src,Image.new('RGB',size,SHADOW)).convert('L')
        sh=diff.point(lambda v:255 if v==0 else 0)
        nonbg=ImageChops.subtract(nonbg,sh)
    return nonbg,sh

class MaskTests(unittest.TestCase):
    def test_exact_masks(self):
        rng=random.Random(34819)
        for _ in range(70):
            w,h=rng.randrange(12,150),rng.randrange(12,150)
            raw=bytearray(rng.randbytes(w*h*3))
            for i in range(0,len(raw),27):
                raw[i:i+3]=BG if (i//27)%2 else SHADOW
            im=Image.frombytes('RGB',(w,h),bytes(raw))
            size=(rng.randrange(10,500),rng.randrange(10,500))
            for shadows in (False, True):
                expected=old_masks(im,size,shadows)
                got=scaled_masks(native_masks(im,BG,SHADOW,shadows),size)
                self.assertEqual(got[0].tobytes(),expected[0].tobytes())
                if shadows:self.assertEqual(got[1].tobytes(),expected[1].tobytes())

if __name__=='__main__':unittest.main()
