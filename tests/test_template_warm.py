import unittest

from detection_review.app import TEMPLATES


class TemplateWarmTests(unittest.TestCase):
    def test_import_compiles_stage1_templates(self):
        names = [key[-1] for key in TEMPLATES.env.cache.keys()]
        self.assertIn("stage1.html", names)
        template = TEMPLATES.env.get_template("stage1.html")
        self.assertEqual(template.name, "stage1.html")
