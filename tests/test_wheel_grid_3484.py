"""Ensure shortened lattice drawing preserves exactly the historical grid."""
import unittest, random
from PIL import Image, ImageDraw

class WheelGridTests(unittest.TestCase):
    def test_visible_lattice_matches_previous_method(self):
        rng=random.Random(123)
        for _ in range(50):
            w=rng.randrange(120,650);h=rng.randrange(80,460)
            ox=rng.randint(-500,500);oy=rng.randint(-500,500)
            old=Image.new('RGB',(w,h),'#505357');d=ImageDraw.Draw(old)
            for slope in (-1,1):
                for c in range(-4*(w+h),4*(w+h)+24,24):
                    d.line([(x,oy+(slope*(x-ox)+c)//2) for x in range(-24,w+25)],fill='#686d71',width=1)
            new=Image.new('RGB',(w,h),'#505357');d=ImageDraw.Draw(new)
            for slope in (-1,1):
                phase=(2*oy-slope*ox-4*(w+h))%24
                x0=-24;x1=w+24
                lo=-48-max(slope*x0,slope*x1)-phase
                hi=2*(h+24)-min(slope*x0,slope*x1)-phase
                for k in range(lo//24-1,hi//24+3):
                    c=phase+24*k
                    d.line([(x,(slope*x+c)//2) for x in range(x0,x1+1)],fill='#686d71',width=1)
            self.assertEqual(old.tobytes(),new.tobytes())

if __name__=='__main__':unittest.main()
