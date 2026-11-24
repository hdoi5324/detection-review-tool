import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from detection_review.study import manifest_from_inputs


def _write_coco(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "images": [{"id": 1, "file_name": "a.jpg", "width": 10, "height": 10}],
                "annotations": [],
                "categories": [{"id": 1, "name": "thing"}],
            }
        )
    )


class DirectInputsTests(unittest.TestCase):
    def test_manifest_from_inputs_minimal(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "images").mkdir()
            (root / "images" / "a.jpg").write_bytes(b"x")
            preds = root / "predictions.json"
            _write_coco(preds)
            manifest = manifest_from_inputs(
                images_dir=root / "images", predictions_coco=preds
            )
            self.assertEqual(manifest.study_id, "review")
            self.assertEqual(len(manifest.datasets), 1)
            spec = manifest.datasets[0]
            self.assertEqual(spec.id, "dataset")
            self.assertIsNone(spec.support_coco)
            self.assertIsNone(spec.ground_truth_coco)

    def test_manifest_from_inputs_with_support_and_gt(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "images").mkdir()
            (root / "images" / "a.jpg").write_bytes(b"x")
            for name in ("predictions.json", "support.json", "gt.json"):
                _write_coco(root / name)
            manifest = manifest_from_inputs(
                study_id="s",
                dataset_id="m",
                images_dir=root / "images",
                predictions_coco=root / "predictions.json",
                support_coco=root / "support.json",
                ground_truth_coco=root / "gt.json",
            )
            spec = manifest.datasets[0]
            self.assertEqual(spec.support_images_dir, spec.images_dir)
            self.assertIsNotNone(spec.ground_truth_coco)

    def test_manifest_from_inputs_missing_predictions(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "images").mkdir()
            with self.assertRaises(FileNotFoundError):
                manifest_from_inputs(
                    images_dir=root / "images",
                    predictions_coco=root / "nope.json",
                )


if __name__ == "__main__":
    unittest.main()
