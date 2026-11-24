import unittest
from pathlib import Path

from detection_review.store import CONFIRMED, DetectionRecord, ReviewStore


def _store() -> ReviewStore:
    cats = [{"id": 1, "name": "octopus"}]
    images = [{"id": 10, "file_name": "a.jpg", "width": 100, "height": 80}]
    det = DetectionRecord(
        id=1,
        image_id=10,
        category_id=1,
        bbox=[2.0, 3.0, 8.0, 9.0],
        label="octopus",
    )
    return ReviewStore(
        dataset_id="ds",
        images_dir=Path("."),
        categories=cats,
        images=images,
        detections={1: det},
        cat_id_to_name={1: "octopus"},
        cat_name_to_id={"octopus": 1},
        image_id_to_meta={10: images[0]},
        image_ids_ordered=[10],
        next_det_id=2,
        counts={
            "confirmed": 0,
            "incorrect": 0,
            "unreviewed": 1,
            "added": 0,
            "resized": 0,
            "deleted": 0,
        },
    )


class ReviewFlagTests(unittest.TestCase):
    def test_round_trip_defaults_false(self):
        det = DetectionRecord(id=1, image_id=1, category_id=1, bbox=[0, 0, 4, 4], label="a")
        raw = det.to_dict()
        self.assertFalse(raw["flagged_for_review"])
        restored = DetectionRecord.from_dict(raw)
        self.assertFalse(restored.flagged_for_review)
        missing = dict(raw)
        missing.pop("flagged_for_review")
        self.assertFalse(DetectionRecord.from_dict(missing).flagged_for_review)

    def test_set_flagged_is_orthogonal_to_status(self):
        store = _store()
        self.assertEqual(store.set_flagged([1], True), 1)
        self.assertTrue(store.detections[1].flagged_for_review)
        self.assertTrue(store.detections[1].is_initial)
        self.assertEqual(store.confirm([1]), 1)
        self.assertEqual(store.detections[1].status, CONFIRMED)
        self.assertTrue(store.detections[1].flagged_for_review)
        self.assertEqual(store.set_flagged([1], True), 0)

    def test_list_patches_flagged_only(self):
        store = _store()
        store.set_flagged([1], True)
        store.add_detection(10, [5, 5, 10, 10], "octopus", flagged_for_review=False)
        all_items = store.list_patches()
        self.assertEqual(all_items["total"], 2)
        flagged = store.list_patches(flagged_only=True)
        self.assertEqual(flagged["total"], 1)
        self.assertTrue(flagged["items"][0]["flagged_for_review"])

    def test_overlay_and_coco_include_flag(self):
        store = _store()
        store.set_flagged([1], True)
        store.confirm([1])
        overlay = store.export_review_overlay()
        self.assertTrue(overlay[0]["flagged_for_review"])
        coco = store.export_coco()
        self.assertTrue(coco["annotations"][0]["flagged_for_review"])
