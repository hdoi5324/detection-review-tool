import json
import unittest
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sponges"
SLICES = ("slice_0_100", "slice_200_300")


def _load(path: Path):
    return json.loads(path.read_text())


class SpongesExampleTests(unittest.TestCase):
    def test_manifest_structure(self):
        manifest = _load(EXAMPLE / "manifest.json")
        self.assertEqual(manifest["study_id"], "sponges_example")
        self.assertEqual(len(manifest["datasets"]), 2)
        ids = {d["id"] for d in manifest["datasets"]}
        self.assertEqual(ids, {"sponges_0_100", "sponges_200_300"})

    def test_files_consistent_and_clean(self):
        support = _load(EXAMPLE / "support.json")
        categories = support["categories"]
        self.assertEqual(
            [c["name"] for c in categories],
            ["Massive Purple", "Fan Pink", "Cup Yellow", "Cup Black Smooth"],
        )
        for name in SLICES:
            for kind in ("predictions.json", "ground_truth.json"):
                coco = _load(EXAMPLE / name / kind)
                self.assertEqual(coco["categories"], categories, f"{name}/{kind}")
                image_ids = {im["id"] for im in coco["images"]}
                self.assertEqual(len(image_ids), 100, f"{name}/{kind}")
                for im in coco["images"]:
                    self.assertNotIn("/", im["file_name"])
                    self.assertNotIn("\\", im["file_name"])
                for ann in coco["annotations"]:
                    self.assertIn(ann["image_id"], image_ids)
                    self.assertNotIn("segmentation", ann)
                    self.assertEqual(len(ann["bbox"]), 4)
                if kind == "predictions.json":
                    self.assertTrue(
                        all("score" in ann for ann in coco["annotations"]),
                        f"{name} predictions must carry scores",
                    )

    def test_support_images_present(self):
        support = _load(EXAMPLE / "support.json")
        self.assertEqual(len(support["images"]), 30)
        for im in support["images"]:
            self.assertNotIn("/", im["file_name"])
            self.assertTrue((EXAMPLE / "support_images" / im["file_name"]).is_file())


if __name__ == "__main__":
    unittest.main()
