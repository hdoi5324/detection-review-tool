import unittest

from detection_review.workload import compute_workload, stage1_decision_count, workload_from_timing


class WorkloadTests(unittest.TestCase):
    def test_stage1_decisions_exclude_adds(self):
        self.assertEqual(
            stage1_decision_count(
                {"confirmed": 30, "added": 5, "incorrect": 20, "unreviewed": 3}
            ),
            45,
        )

    def test_example_fit(self):
        out = compute_workload(
            t1_sec=100,
            t2_sec=80,
            counts={"confirmed": 30, "added": 5, "incorrect": 20, "unreviewed": 3},
            n_images=10,
            gt_fn=6,
        )
        self.assertEqual(out["n_s1"], 45)
        self.assertEqual(out["n_confirmed_model"], 25)
        self.assertAlmostEqual(out["w_sec"], 180.0)
        self.assertAlmostEqual(out["beta_s_per_decision"], round(100 / 45, 3))
        self.assertAlmostEqual(out["alpha_s_per_image"], 8.0)
        self.assertAlmostEqual(out["alpha_s_per_fn"], 16.0)
        self.assertAlmostEqual(out["rho"], 3.6)
        self.assertAlmostEqual(out["stage1_share"], round(100 / 180, 4))
        self.assertEqual(out["display"]["w"], "180.0s")
        self.assertEqual(out["display"]["beta"], "2.2s / decision")
        self.assertEqual(out["display"]["alpha_img"], "8.0s / image")
        self.assertEqual(out["display"]["alpha_fn"], "16.0s / miss")
        self.assertEqual(out["display"]["rho"], "3.6×")
        self.assertIn("unmatched (FN)", out["display"]["gt_line"])
        self.assertIn("added 5 boxes", out["display"]["gt_line"])

    def test_no_adds_omits_per_miss_rate(self):
        out = compute_workload(
            t1_sec=50,
            t2_sec=40,
            counts={"confirmed": 10, "added": 0, "incorrect": 5},
            n_images=8,
        )
        self.assertIsNone(out["alpha_s_per_fn"])
        self.assertEqual(out["display"]["alpha_fn"], "—")
        self.assertAlmostEqual(out["alpha_s_per_image"], 5.0)
        self.assertIsNone(out["display"]["gt_line"])

    def test_no_stage1_decisions_omits_beta_and_ratio(self):
        out = compute_workload(
            t1_sec=12,
            t2_sec=30,
            counts={"confirmed": 4, "added": 4, "incorrect": 0},
            n_images=3,
        )
        self.assertEqual(out["n_s1"], 0)
        self.assertIsNone(out["beta_s_per_decision"])
        self.assertIsNone(out["rho"])
        self.assertEqual(out["display"]["beta"], "—")
        self.assertEqual(out["display"]["rho"], "—")
        self.assertAlmostEqual(out["alpha_s_per_image"], 10.0)

    def test_missing_times_are_zero(self):
        out = compute_workload(
            t1_sec=None,
            t2_sec=None,
            counts={"confirmed": 2, "added": 0, "incorrect": 2},
            n_images=4,
        )
        self.assertEqual(out["w_sec"], 0.0)
        self.assertEqual(out["beta_s_per_decision"], 0.0)
        self.assertEqual(out["alpha_s_per_image"], 0.0)

    def test_from_timing_json(self):
        out = workload_from_timing(
            {
                "stage1": {"elapsed_sec": 100},
                "stage2": {"elapsed_sec": 80},
                "counts": {"confirmed": 30, "added": 5, "incorrect": 20},
                "n_images": 10,
                "gt_comparison": {"fn": 6},
            }
        )
        self.assertAlmostEqual(out["w_sec"], 180.0)
        self.assertEqual(out["gt_fn"], 6)
        self.assertEqual(out["n_s1"], 45)


if __name__ == "__main__":
    unittest.main()
