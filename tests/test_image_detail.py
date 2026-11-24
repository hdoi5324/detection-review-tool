import unittest
from pathlib import Path

from detection_review.store import DetectionRecord, ReviewStore


def _store_with_boxes(*records: DetectionRecord) -> ReviewStore:
    cats = [{"id": 1, "name": "urchin"}]
    images = [{"id": 10, "file_name": "a.jpg", "width": 100, "height": 80}]
    return ReviewStore(
        dataset_id="d",
        images_dir=Path("."),
        categories=cats,
        images=images,
        detections={r.id: r for r in records},
        cat_id_to_name={1: "urchin"},
        cat_name_to_id={"urchin": 1},
        image_id_to_meta={10: images[0]},
        image_ids_ordered=[10],
        next_det_id=max((r.id for r in records), default=0) + 1,
    )


class ImageDetailScoreTests(unittest.TestCase):
    def test_get_image_detail_includes_score(self):
        store = _store_with_boxes(
            DetectionRecord(
                id=1,
                image_id=10,
                category_id=1,
                bbox=[1, 2, 3, 4],
                label="urchin",
                score=0.42,
            ),
            DetectionRecord(
                id=2,
                image_id=10,
                category_id=1,
                bbox=[5, 6, 7, 8],
                label="urchin",
                score=None,
            ),
        )
        detail = store.get_image_detail(10)
        by_id = {b["id"]: b for b in detail["boxes"]}
        self.assertEqual(by_id[1]["score"], 0.42)
        self.assertIsNone(by_id[2]["score"])
        self.assertIn("source", by_id[1])


class DeleteDetectionsTests(unittest.TestCase):
    def test_delete_detections_skips_missing_and_counts(self):
        store = _store_with_boxes(
            DetectionRecord(
                id=1,
                image_id=10,
                category_id=1,
                bbox=[1, 2, 3, 4],
                label="urchin",
            ),
            DetectionRecord(
                id=2,
                image_id=10,
                category_id=1,
                bbox=[5, 6, 7, 8],
                label="urchin",
            ),
        )
        n = store.delete_detections([1, 2, 99])
        self.assertEqual(n, 2)
        self.assertNotIn(1, store.detections)
        self.assertNotIn(2, store.detections)


if __name__ == "__main__":
    unittest.main()
