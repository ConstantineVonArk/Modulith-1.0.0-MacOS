"""Checks for UI-only changes to the toolbar artwork thumbnails."""
import unittest
from pathlib import Path
from PIL import Image
from toolbar_icons import thumbnail

class ToolbarIcons3489(unittest.TestCase):
    def test_all_icons_fit_same_toolbar_size(self):
        icons=sorted((Path(__file__).parent/'library'/'toolbar').glob('*.png'))
        self.assertGreaterEqual(len(icons),25)
        for path in icons:
            with self.subTest(icon=path.name):
                with Image.open(path) as source:
                    self.assertEqual(thumbnail(source,31).size,(31,31))
                    self.assertEqual(thumbnail(source,32).size,(32,32))

    def test_source_not_mutated(self):
        path=Path(__file__).parent/'library'/'toolbar'/'module_decor.png'
        with Image.open(path) as source:
            before=source.tobytes()
            thumb=thumbnail(source,31)
            self.assertEqual(source.tobytes(),before)
            self.assertEqual(thumb.mode,'RGBA')

if __name__=='__main__':unittest.main()
