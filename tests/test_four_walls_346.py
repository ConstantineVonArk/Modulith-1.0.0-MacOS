"""V3.46 regression: four independent wall masters and per-wall edit grids."""
import os, sys, unittest
from types import SimpleNamespace
from PIL import Image
import volume_editor as ve

class Var:
    def __init__(self,v): self.v=v
    def get(self):return self.v

class FourWalls(unittest.TestCase):
    def test_all_faces_get_independent_artwork(self):
        colors={'front':(220,65,65),'back':(65,195,90),
                'left':(65,115,230),'right':(230,185,40)}
        masters={}
        for wall,rgb in colors.items():
            masters[wall]={'iso':Image.new('RGBA',(80,130),rgb+(255,)),
                           'front':Image.new('RGBA',(100,100),rgb+(255,))}
        b=ve.Block(w=80,d=80,h=50,rise=0)
        seen=set()
        for angle in range(0,360,15):
            im=ve.render_scene([b],angle=angle,facade_source=masters['front']['iso'],
               facade_front=masters['front']['front'],wall_facades=masters)
            for rgb in im.getdata():
                for wall,target in colors.items():
                    # Wall colours may be attenuated by the game's art lighting.
                    if abs(rgb[0]-target[0])<60 and abs(rgb[1]-target[1])<60 and abs(rgb[2]-target[2])<60:
                        seen.add(wall)
        self.assertEqual(seen,set(colors))

    def test_side_grid_controls_cut_not_front_grid(self):
        block=ve.Block(w=100,d=40,h=50,rise=0)
        selected={(0,'left',2,0),(0,'left',2,1)}
        counts={'front':[6]*4,'left':[3]*4}
        limits=[(i/3,(i+1)/3) for i in range(3)]
        dummy=SimpleNamespace(
            selected_modules=selected, module_layout={'floors':4,'counts':[6]*4,'spans':None},
            wall_layouts={'left':{'floors':4,'counts':[3]*4,'spans':[limits]*4}},
            blocks=[block], edit_depth=Var(-5),portico_count=Var(4),
            portico_style=Var(1),portico_columns=Var(False),cut_to_edges=Var(False),
            wall_edits=[], _cache_key=None,
            schedule=lambda:None,update_context_preview=lambda:None)
        ve.App.apply_selected_wall_edit(dummy)
        cut=dummy.wall_edits[0]
        self.assertEqual(cut['wall'],'left')
        self.assertAlmostEqual(cut['t0'],0.)
        self.assertAlmostEqual(cut['t1'],2/3)
        self.assertAlmostEqual(cut['z0'],25.)
        self.assertAlmostEqual(cut['z1'],37.5)
        # The actual boolean geometry must also work on that left wall.
        original=ve.scene_mesh([block],2)
        cutmesh=ve.apply_wall_edits(original,[block],dummy.wall_edits)
        self.assertTrue(cutmesh)
        self.assertNotEqual(len(cutmesh),len(original))

if __name__=='__main__':unittest.main(verbosity=2)
