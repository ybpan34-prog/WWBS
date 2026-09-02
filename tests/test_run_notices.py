import unittest

from PIL import Image

from app import RUN_NOTICES


class RunNoticeTests(unittest.TestCase):
    def test_all_run_notice_images_are_packaged_sixteen_by_nine(self):
        self.assertEqual(set(RUN_NOTICES), {"daily", "weekly", "combat_4c"})
        for title, image_path in RUN_NOTICES.values():
            self.assertTrue(image_path.exists(), title)
            with Image.open(image_path) as image:
                self.assertEqual(image.size, (960, 540), title)

    def test_run_notices_do_not_show_numbered_image_captions(self):
        self.assertTrue(all(len(notice) == 2 for notice in RUN_NOTICES.values()))


if __name__ == "__main__":
    unittest.main()
