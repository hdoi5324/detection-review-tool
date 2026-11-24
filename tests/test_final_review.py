import json
import tempfile
import unittest
from pathlib import Path

from detection_review.persist import load_completed_results
from detection_review.store import CONFIRMED, DatasetRun, DetectionRecord, ReviewStore


def _store(images_dir: Path) -> ReviewStore:
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
        dataset_id="ds1",
        images_dir=images_dir,
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


class FinalReviewPersistTests(unittest.TestCase):
    def test_complete_freezes_reviewed_and_later_edits_write_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            images_dir = Path(tmp) / "images"
            images_dir.mkdir()
            store = _store(images_dir)
            run = DatasetRun(
                study_id="study",
                tester="t",
                dataset_id="ds1",
                run_dir=run_dir,
                store=store,
            )
            store.confirm([1])
            run.write_timing()
            run.freeze_reviewed_snapshot()
            reviewed_coco = json.loads(run.reviewed_coco_path().read_text())
            reviewed_state = json.loads(run.reviewed_state_snapshot_path().read_text())
            self.assertEqual(len(reviewed_coco["annotations"]), 1)
            self.assertFalse(reviewed_state["detections"][0]["flagged_for_review"])

            run.completed = True
            run.write_timing(write_store=False)
            store.set_flagged([1], True)
            store.add_detection(10, [20, 20, 12, 12], "octopus")
            run.write_timing()

            after_reviewed = json.loads(run.reviewed_coco_path().read_text())
            self.assertEqual(after_reviewed, reviewed_coco)
            self.assertTrue(run.final_coco_path().is_file())
            final_coco = json.loads(run.final_coco_path().read_text())
            self.assertEqual(len(final_coco["annotations"]), 2)
            final_state = json.loads(run.final_review_state_path().read_text())
            flagged = {d["id"]: d["flagged_for_review"] for d in final_state["detections"]}
            self.assertTrue(flagged[1])

            preds = {
                "categories": store.categories,
                "images": store.images,
                "annotations": [
                    {
                        "id": 1,
                        "image_id": 10,
                        "category_id": 1,
                        "bbox": [2.0, 3.0, 8.0, 9.0],
                        "score": 0.9,
                    }
                ],
            }
            pred_path = Path(tmp) / "preds.json"
            pred_path.write_text(json.dumps(preds))
            loaded = DatasetRun.load(
                run_dir,
                images_dir=images_dir,
                predictions_path=pred_path,
                close_open_timers=True,
            )
            self.assertTrue(loaded.completed)
            self.assertTrue(loaded.store.detections[1].flagged_for_review)
            self.assertEqual(len(loaded.store.detections), 2)

            results = load_completed_results(run_dir)
            self.assertEqual(results["results_source"], "qaqc")
            self.assertTrue(results["has_qaqc"])
            self.assertEqual(results["counts"]["confirmed"], 2)
            self.assertTrue(str(results["exported"]["coco"]).endswith("instances_final.json"))
            self.assertTrue(
                str(results["views"]["timed"]["exported"]["coco"]).endswith("instances_reviewed.json")
            )
            self.assertTrue(
                str(results["views"]["qaqc"]["exported"]["coco"]).endswith("instances_final.json")
            )
            self.assertEqual(results["views"]["timed"]["counts"]["confirmed"], 1)
            self.assertEqual(results["views"]["qaqc"]["counts"]["confirmed"], 2)

    def test_results_use_reviewed_until_final_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            images_dir = Path(tmp) / "images"
            images_dir.mkdir()
            store = _store(images_dir)
            run = DatasetRun(
                study_id="study",
                tester="t",
                dataset_id="ds1",
                run_dir=run_dir,
                store=store,
            )
            store.confirm([1])
            run.write_timing()
            run.freeze_reviewed_snapshot()
            run.completed = True
            run.write_timing(write_store=False)
            results = load_completed_results(run_dir)
            self.assertEqual(results["results_source"], "timed")
            self.assertFalse(results["has_qaqc"])
            self.assertTrue(str(results["exported"]["coco"]).endswith("instances_reviewed.json"))
            self.assertEqual(results["counts"]["confirmed"], 1)
            self.assertEqual(CONFIRMED, store.detections[1].status)
