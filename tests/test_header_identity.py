import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from detection_review.session_source import (
    MANIFEST_SOURCE,
    HeaderField,
    HeaderIdentity,
    header_identity,
    stamp_session,
)

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "detection_review" / "templates"


class HeaderIdentityTests(unittest.TestCase):
    def test_manifest_shows_tester_study_and_dataset(self):
        ident = header_identity(
            {"source": MANIFEST_SOURCE, "tester": "alice", "study_id": "urchin"},
            progress={
                "study_id": "urchin",
                "tester": "alice",
                "index": 0,
                "total": 5,
                "current_dataset_id": "nuggets",
                "complete": False,
            },
        )
        self.assertEqual(ident.source, MANIFEST_SOURCE)
        self.assertEqual(ident.title, HeaderField("Study", "urchin"))
        self.assertEqual(ident.detail, "Tester: alice · Model: nuggets · Model no: 1 of 5")
        self.assertEqual(ident.person, "alice")

    def test_stamp_session_sets_shared_keys(self):
        session = {}
        stamp_session(session, MANIFEST_SOURCE, tester="alice", study_id="urchin")
        self.assertEqual(session["source"], MANIFEST_SOURCE)
        self.assertEqual(session["tester"], "alice")
        self.assertEqual(session["study_id"], "urchin")


class ResultsTemplateTests(unittest.TestCase):
    def setUp(self):
        self.env = Environment(loader=FileSystemLoader(str(TEMPLATES)))

    def _render_results(self, **overrides):
        ctx = dict(
            asset_v="1",
            stage="results",
            progress={
                "complete": False,
                "tester": "alice",
                "study_id": "urchin",
                "index": 1,
                "total": 3,
                "current_dataset_id": "nuggets",
            },
            header=HeaderIdentity(
                source=MANIFEST_SOURCE,
                title=HeaderField("Study", "urchin"),
                fields=(
                    HeaderField("Tester", "alice"),
                    HeaderField("Model", "nuggets"),
                    HeaderField("Model no", "1 of 3"),
                ),
                person="alice",
            ),
            gt=None,
            gt_original=None,
            metric_rows=[],
            class_rows=[],
            counts={},
            timing={"stage1": None, "stage2": None},
            categories=[],
        )
        ctx.update(overrides)
        return self.env.get_template("results.html").render(**ctx)

    def test_next_dataset_cta_is_above_metrics(self):
        html = self._render_results()
        self.assertLess(html.find("Next model"), html.find("Your edits"))
        self.assertLess(html.find("results-cta"), html.find("Your edits"))
        self.assertIn("Tester:", html)
        self.assertIn("alice", html)
        self.assertIn("Model:", html)
        self.assertIn("nuggets", html)
        self.assertIn("Model no:", html)
        self.assertIn("1 of 3", html)
        self.assertEqual(html.count("Next model"), 1)

    def test_results_compare_toggle_defaults_to_qaqc(self):
        html = self._render_results(has_qaqc=True, compare="qaqc")
        self.assertIn("Report compared to", html)
        self.assertIn("/results?compare=qaqc", html)
        self.assertIn("/results?compare=timed", html)
        self.assertIn("Showing QA/QC review compared to ground truth.", html)
        self.assertIn("QA/QC review", html)
        self.assertIn("Timed Review", html)

    def test_results_without_qaqc_has_no_compare_toggle(self):
        html = self._render_results(has_qaqc=False, compare="timed")
        self.assertNotIn("Report compared to", html)
        self.assertIn("Showing Timed Review compared to ground truth.", html)
        self.assertIn("QA/QC review", html)

    def test_dataset_filter_appends_to_header_line(self):
        html = self.env.get_template("_header.html").render(
            stage="stage1",
            progress={"study_id": "urchin", "tester": "alice", "total": 1},
            header=HeaderIdentity(
                source=MANIFEST_SOURCE,
                title=HeaderField("Study", "urchin"),
                fields=(
                    HeaderField("Tester", "alice"),
                    HeaderField("Model", "nuggets"),
                ),
                person="alice",
            ),
            dataset_filter="Top 50 per image · score > 0.1",
        )
        dataset_line = html[html.find("dataset-line") :]
        self.assertIn("Tester", dataset_line)
        self.assertIn("nuggets", dataset_line)
        self.assertIn("Top 50 per image", dataset_line)
        self.assertIn("score > 0.1", dataset_line)
        self.assertGreater(dataset_line.find("nuggets"), 0)
        self.assertGreater(dataset_line.find("Top 50 per image"), dataset_line.find("nuggets"))

    def test_login_template_shows_study_dropdown(self):
        html = self.env.get_template("login.html").render(
            asset_v="1",
            studies=[{"study_id": "urchin"}],
            selected_study_id=None,
            skip_dropdown=False,
            tester="",
            error=None,
        )
        self.assertIn("Choose a study", html)
        self.assertIn("urchin", html)


if __name__ == "__main__":
    unittest.main()
