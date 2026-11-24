# Architecture & provenance

## Where this repo comes from

This repository is a **frozen public snapshot** of the review tool used for
the user studies accompanying our few-shot object detection paper. It was
exported on 2026-11-24 from the private working repository
`timed-detection-review` at commit:

```
1245d9ab893b84a8153e925d822443a13744e8de  (branch: dev)
```

The private repository remains the canonical home of the full study system
(additional integrations and study operations that are not part of the
published tool). This snapshot contains only the standalone review tool:
COCO predictions + image directories in, reviewed COCO + timings out.

Files were copied, the package was renamed (`timed_review` →
`detection_review`), private integrations were removed, and a direct-input
CLI (`--images-dir` / `--predictions-coco` / …) was added. The public repo
is thereafter maintained on its own; it is **not** auto-synced.

## Porting a future fix from the private repository

1. In the private repository, list what changed since the snapshot:
   `git diff 1245d9ab893b84a8153e925d822443a13744e8de..HEAD -- src/`
   (adjust the path if the private layout changes).
2. Apply the relevant hunks here by hand, skipping anything tied to the
   private integrations. Expect `app.py`, `store.py`, `static/` and
   `templates/` to be the usual port targets; hunks that only touch
   modules absent here can be ignored.
3. Re-run the publication checks: the private-reference grep in CI
   (`.github/workflows/ci.yml`), `python -m compileall -q src scripts tests`,
   and `pytest`.
4. Update the commit hash above to the new source commit and note the port
   in the commit message.

If ports become frequent (more than a few substantive updates a year),
revisit splitting the private app along the same seams instead.

## Core boundaries

- `store.py`: in-memory review state built from a predictions COCO file;
  no web or filesystem-layout assumptions beyond an image directory.
- `study.py`: what a study is — a list of datasets, each an image
  directory + predictions file with optional support and ground truth.
  Studies come from a manifest file or from direct CLI inputs
  (`manifest_from_inputs`).
- `app.py`: FastAPI routes and session/run lifecycle. Runs are persisted
  under `outputs/review_runs/` by `persist.py`/`store.py` so reviewers can
  resume; nothing is kept only in memory across restarts by design.
- `gt_eval.py`: reviewed-vs-ground-truth matching (IoU, one-to-one) and
  COCO-style AP; used on completion and on the results page.
- `examples/sponges/` is data, not code: predictions generated once with
  the SAM3-FSOD method (see README) and frozen. Regenerate only with
  `scripts/build_sponges_example.py` and expect review timings/metrics
  quoted anywhere to change if the predictions change.
