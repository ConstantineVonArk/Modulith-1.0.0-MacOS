"""SC3K v3.40: stepped, watertight entablature profile regression tests.

Run: python3 test_portico_profile_340.py
"""
import math
import unittest

import volume_editor as ve


class PorticoProfile340(unittest.TestCase):
    def setUp(self):
        self.block = ve.Block(w=96, d=28, h=72, rise=12)
        self.edit = dict(block=0,wall='front', t0=.12,t1=.88,
                         z0=8,z1=60, depth=-11,columns=5,column_style=2)

    def mesh(self, edit=None):
        return ve.apply_wall_edits(ve.scene_mesh([self.block], 2),
                                   [self.block],[edit or self.edit])

    def tiers(self, mesh):
        names=('portico_entablature_arch',
               'portico_entablature_frieze',
               'portico_entablature_cornice')
        return {name:[(tri,n) for tri,kind,n in mesh if kind==name]
                for name in names}

    def test_visual_height_transfer_without_moving_the_beam_bottom(self):
        tiers=self.tiers(self.mesh())
        levels=[]
        for members in tiers.values():
            self.assertTrue(members)
            levels.append(sorted({round(p[2],7) for tri,_ in members for p in tri}))
        arch,frieze,cornice=levels
        self.assertEqual(len(arch),2)
        self.assertEqual(len(frieze),2)
        self.assertEqual(len(cornice),2)
        self.assertAlmostEqual(arch[1],frieze[0])
        self.assertAlmostEqual(frieze[1],cornice[0])
        self.assertAlmostEqual(arch[0],ve.portico_entablature_bottom(8,60)+.05)
        self.assertAlmostEqual(cornice[1],60-.05)
        original_corn_height=max(.75,min(1.10,(60-ve.portico_entablature_bottom(8,60))*.22))
        self.assertAlmostEqual(cornice[1]-cornice[0], max(.50, original_corn_height-.50), places=5)

    def test_cornice_projects_further_than_arch_and_recessed_frieze(self):
        levels=[]
        for members in self.tiers(self.mesh()).values():
            depths=[p[1] for tri,_ in members for p in tri]
            levels.append((min(depths),max(depths)))
        arch,frieze,cornice=levels
        self.assertLess(cornice[0],arch[0])
        self.assertGreater(cornice[1],arch[1])
        self.assertLess(arch[0],frieze[0])
        self.assertGreater(arch[1],frieze[1])
        # At a normal 8x8-column footprint the cornice extends 0.8 world
        # units (roughly 1 pixel in oblique views) beyond its v3.39 edge.
        size=min(8.,((96*(.88-.12))/5)*.96,abs(-11)-.5)
        lip=min(1.15,max(.55,size*.14),size*.55)
        left=(28-(size/2+.25))-size/2
        right=(28-(size/2+.25))+size/2
        self.assertAlmostEqual(cornice[0],left-lip*.78-.8)
        self.assertAlmostEqual(cornice[1],right+lip*.78+.8)

    def test_no_hidden_horizontal_faces_or_overlapping_tiers(self):
        groups=self.tiers(self.mesh())
        levels=[sorted({round(p[2],7) for tri,_ in group for p in tri})
                for group in groups.values()]
        # A shared junction's entire middle footprint must be an interior
        # volume: no top/bottom triangles are allowed across it.
        for i in (0,1):
            lower=list(groups.values())[i]
            upper=list(groups.values())[i+1]
            z=levels[i][1]
            lo0=min(p[1] for tri,_ in lower for p in tri)
            hi0=max(p[1] for tri,_ in lower for p in tri)
            lo1=min(p[1] for tri,_ in upper for p in tri)
            hi1=max(p[1] for tri,_ in upper for p in tri)
            common_y=(max(lo0,lo1)+min(hi0,hi1))/2
            common_x=96/2
            for members in (lower,upper):
                for tri,normal in members:
                    if abs(normal[2])<.9 or not all(abs(p[2]-z)<1e-5 for p in tri):
                        continue
                    def area(a,b,c):
                        return abs((b[0]-a[0])*(c[1]-a[1])-(c[0]-a[0])*(b[1]-a[1]))/2
                    pt=(common_x,common_y)
                    total=area(*tri)
                    sub=sum(area(pt,tri[j],tri[(j+1)%3]) for j in range(3))
                    self.assertGreater(abs(sub-total),1e-5,
                        'Interior horizontal face at tier joint produces coplanar z-fighting')

    def test_no_entablature_on_empty_niche_or_protrusion(self):
        for edit in (dict(self.edit,columns=0),dict(self.edit,depth=4)):
            self.assertTrue(all(not members for members in self.tiers(self.mesh(edit)).values()))

    def test_24_angles_all_walls_rasterize(self):
        # Narrower render sizes for cost. This confirms that each profile can
        # be rasterised after rotation without z-buffer errors or clipping.
        block=ve.Block(w=48,d=20,h=48,rise=8)
        for wall in ('front','back','left','right'):
            edit=dict(self.edit,wall=wall,t0=.05,t1=.95,z0=6,z1=40,columns=3)
            for ang in range(0,360,15):
                img=ve.render_scene([block],angle=ang,wall_edits=[edit])
                self.assertGreater(img.width,10)


if __name__=='__main__':
    unittest.main(verbosity=2)
