"""Regression for procedural entablature and edge-anchored columns (v3.37)."""
import unittest
import volume_editor as ve

class PorticoEntablature337(unittest.TestCase):
    def setUp(self):
        self.body=ve.Block(w=84,d=24,h=68,rise=12)
        self.edit=dict(block=0,wall='front',t0=.14,t1=.86,z0=10,z1=58,depth=-11,columns=4,column_style=2)

    def test_entablature_exists_only_for_columned_recess(self):
        mesh=ve.apply_wall_edits(ve.scene_mesh([self.body],2),[self.body],[self.edit])
        self.assertGreater(sum(kind in ('portico_entablature_arch','portico_entablature_frieze','portico_entablature_cornice') for tri,kind,n in mesh),0)
        for edits in ([dict(self.edit,columns=0)],[dict(self.edit,depth=4)],[]):
            mesh=ve.apply_wall_edits(ve.scene_mesh([self.body],2),[self.body],edits)
            self.assertEqual(sum(kind in ('portico_entablature_arch','portico_entablature_frieze','portico_entablature_cornice') for tri,kind,n in mesh),0)

    def test_edge_columns_touch_side_bounds(self):
        mesh=ve.apply_wall_edits(ve.scene_mesh([self.body],2),[self.body],[self.edit])
        plinth=[tri for tri,kind,n in mesh if kind=='portico_plinth']
        verts=sorted({(round(p[0],6),round(p[1],6),round(p[2],6)) for tri in plinth for p in tri})
        xs=sorted({p[0] for p in verts})
        # Front opening along X on the front wall. Supports should touch its bounds.
        a0=self.body.x+self.body.w*self.edit['t0']
        a1=self.body.x+self.body.w*self.edit['t1']
        self.assertAlmostEqual(xs[0],a0,places=4)
        self.assertAlmostEqual(xs[-1],a1,places=4)

if __name__=="__main__":
    unittest.main(verbosity=2)
