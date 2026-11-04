"""Compatibility checks for the mechanically extracted sprite module."""
import unittest
import volume_editor as old
import sprite_assets as assets

class AssetExtractionTest(unittest.TestCase):
    def test_public_names_reexported(self):
        for name in ('column_part_sprite','column_capital_source',
                     'projected_column_capital','capital_angle_mapping',
                     'tile_sprite_y','dormer_window_sprite'):
            self.assertIs(getattr(old,name),getattr(assets,name))

    def test_cache_identity(self):
        self.assertIs(old._COLUMN_CACHE,assets._COLUMN_CACHE)
        self.assertIs(old._DORMER_CACHE,assets._DORMER_CACHE)

    def test_asset_paths(self):
        self.assertTrue(assets.COLUMN_SPRITES_PATH.is_dir())
        for style in (1,2,3):
            for mode in ('iso','front','profile'):
                self.assertIsNotNone(old.column_capital_source(style,mode))

if __name__=='__main__':unittest.main()
