"""Geometry cache should reuse repeated roofs yet invalidate after any block edit."""
import unittest
from volume_editor import Block, scene_mesh, _cached_scene_mesh, _scene_mesh_uncached

class GeometryCacheTests(unittest.TestCase):
    def test_reuse_and_invalidation(self):
        b=Block(w=64,d=40,h=48,rise=16)
        _cached_scene_mesh.cache_clear()
        first=scene_mesh([b],2)
        self.assertEqual(first,_scene_mesh_uncached([b],2))
        for _ in range(4):
            self.assertEqual(scene_mesh([b],2),first)
        info=_cached_scene_mesh.cache_info()
        self.assertEqual(info.misses,1)
        self.assertGreaterEqual(info.hits,4)
        for name,value in [('w',68),('d',44),('rise',19),('roof_type','Четырёхскатная'),('overhang',3)]:
            setattr(b,name,value)
            self.assertEqual(scene_mesh([b],2),_scene_mesh_uncached([b],2))
        self.assertEqual(_cached_scene_mesh.cache_info().misses,6)

    def test_cached_result_not_mutated_by_caller(self):
        b=Block()
        a=scene_mesh([b],2)
        n=len(a)
        a.clear()
        self.assertEqual(len(scene_mesh([b],2)),n)

if __name__=='__main__':unittest.main()
