"""Regression checks for the geometric one-pixel portico abacus (v3.36)."""
import math
import unittest
from collections import Counter
from PIL import Image
import volume_editor as ve


class PorticoAbacus336(unittest.TestCase):
    def setUp(self):
        self.body=ve.Block(w=72,d=22,h=66,rise=11)
        self.edit=dict(block=0,wall='front',t0=.15,t1=.85,
                       z0=10,z1=57,depth=-11,columns=3,column_style=2)

    def test_paired_square_supports_same_size_and_centres(self):
        mesh=ve.apply_wall_edits(ve.scene_mesh([self.body],2),[self.body],[self.edit])
        support={k:[tri for tri,kind,n in mesh if kind==k]
                 for k in ('portico_plinth','portico_abacus')}
        # 12 triangles (6 faces x 2 triangles) per each of the 3 columns.
        for tris in support.values():
            self.assertEqual(len(tris),36)
        for k,triangles in support.items():
            verts={tuple(round(v,6) for v in point)
                   for tri in triangles for point in tri}
            zs=sorted({p[2] for p in verts})
            self.assertEqual(len(zs),2)
            self.assertAlmostEqual(zs[1]-zs[0],.5)
            if k=='portico_plinth':
                self.assertAlmostEqual(zs[0],self.edit['z0']+.05)
            else:
                self.assertAlmostEqual(zs[1],ve.portico_entablature_bottom(self.edit['z0'],self.edit['z1'])-.05)
            xy={(p[0],p[1]) for p in verts}
            if k=='portico_plinth':
                low_xy=xy
            else:
                self.assertEqual(xy,low_xy)
            self.assertLessEqual(max(p[2] for p in verts),self.edit['z1'])
            self.assertGreaterEqual(min(p[2] for p in verts),self.edit['z0'])

    def test_no_abacus_for_plain_niche_or_extrusion(self):
        for edits in ([dict(self.edit,columns=0)],
                      [dict(self.edit,depth=5)], []):
            mesh=ve.apply_wall_edits(ve.scene_mesh([self.body],2),[self.body],edits)
            self.assertEqual(sum(kind=='portico_abacus' for t,kind,n in mesh),0)

    def test_all_styles_and_views(self):
        for style in (1,2,3):
            for angle in (0,30,45,90,135,180,225,270,315,345):
                with self.subTest(style=style,angle=angle):
                    img=ve.render_scene([self.body], angle=angle,
                                        wall_edits=[dict(self.edit,column_style=style)])
                    self.assertIsInstance(img,Image.Image)
                    self.assertGreater(img.width,30)


if __name__=='__main__':
    unittest.main(verbosity=2)
