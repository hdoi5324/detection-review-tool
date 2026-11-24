from __future__ import annotations

import argparse
import faulthandler
import os
import sys
from pathlib import Path


def _default_config_path() -> Path | None:
    for guess in (Path("config/review_config.json"), Path("studies/review_config.json")):
        if guess.is_file():
            return guess
    return None


def main(argv: list[str] | None = None) -> None:
    faulthandler.enable(file=sys.stderr, all_threads=True)
    from detection_review.config import load_project_env

    load_project_env()
    parser = argparse.ArgumentParser(
        description="Detection Review Tool server: two-stage timed review of "
        "detection predictions (COCO format) against an image directory."
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=None,
        help="Directory of query images (direct-input mode; requires --predictions-coco)",
    )
    parser.add_argument(
        "--predictions-coco",
        type=Path,
        default=None,
        help="COCO-format predictions file to review (direct-input mode)",
    )
    parser.add_argument(
        "--support-coco",
        type=Path,
        default=None,
        help="Optional COCO support/exemplar file; its annotations are shown "
        "as class examples in Stage 1 (direct-input mode)",
    )
    parser.add_argument(
        "--support-images-dir",
        type=Path,
        default=None,
        help="Directory containing the support images (default: --images-dir)",
    )
    parser.add_argument(
        "--ground-truth-coco",
        type=Path,
        default=None,
        help="Optional COCO ground-truth file; enables precision/recall "
        "comparison on the results page (direct-input mode)",
    )
    parser.add_argument(
        "--study-id",
        default="review",
        help="Study id for direct-input mode (default: review)",
    )
    parser.add_argument(
        "--dataset-id",
        default="dataset",
        help="Dataset/model id for direct-input mode (default: dataset)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Single study manifest JSON (alternative to direct inputs). If this "
        "is the only source, login skips the study dropdown. May be combined "
        "with --manifest-dir to preselect one study.",
    )
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=None,
        help="Directory of study manifests. Login shows a study_id dropdown.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Review config JSON (stage1_top_n, stage1_min_score, stage1_tour, "
        "stage2_tour). Defaults to config/review_config.json if present.",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data"),
        help="Cache directory for thumbnails and exemplar crops (default: data)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs"),
        help="Where review runs are written (default: outputs). "
        "Creates outputs/review_runs/<study_id>/<tester>/...",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("REVIEW_PASSWORD", "review"),
        help="Shared review password (default: review or REVIEW_PASSWORD)",
    )
    args = parser.parse_args(argv)

    direct = args.images_dir is not None or args.predictions_coco is not None
    if direct and (args.images_dir is None or args.predictions_coco is None):
        parser.error("--images-dir and --predictions-coco must be given together")
    if not direct and args.manifest is None and args.manifest_dir is None:
        parser.error(
            "provide --images-dir/--predictions-coco, or --manifest/--manifest-dir"
        )
    if direct and (args.manifest is not None or args.manifest_dir is not None):
        parser.error("direct inputs cannot be combined with --manifest/--manifest-dir")

    os.environ["REVIEW_PASSWORD"] = args.password
    os.environ["DATA_ROOT"] = str(args.data_root.resolve())
    os.environ["OUTPUT_DIR"] = str(args.output_dir.resolve())

    config_path = args.config if args.config is not None else _default_config_path()

    import uvicorn
    from detection_review.app import create_app
    from detection_review.config import ReviewConfig
    from detection_review.study import build_catalog, manifest_from_inputs

    manifests = None
    if direct:
        try:
            manifest = manifest_from_inputs(
                study_id=args.study_id,
                dataset_id=args.dataset_id,
                images_dir=args.images_dir,
                predictions_coco=args.predictions_coco,
                support_coco=args.support_coco,
                support_images_dir=args.support_images_dir,
                ground_truth_coco=args.ground_truth_coco,
            )
        except (FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))
        manifests = {manifest.study_id: manifest}
        catalog, locked = {}, manifest.study_id
    else:
        catalog, locked = build_catalog(manifest=args.manifest, manifest_dir=args.manifest_dir)
    cfg = ReviewConfig.load(config_path)

    app = create_app(
        catalog=catalog,
        locked_study_id=locked,
        data_root=args.data_root.resolve(),
        output_root=args.output_dir.resolve(),
        password=args.password,
        config_path=config_path,
        manifests=manifests,
    )
    studies = ", ".join(catalog or manifests or {})
    lock_note = f"  locked study: {locked}\n" if locked and args.manifest_dir is None else ""
    print(
        f"Study catalog ready. Open http://{args.host}:{args.port}/\n"
        f"  studies: {studies}\n"
        f"{lock_note}"
        f"  (password={args.password})\n"
        f"  outputs: {args.output_dir.resolve() / 'review_runs'}\n"
        f"  cache: {args.data_root.resolve() / 'cache'}\n"
        f"  stage1_top_n={cfg.stage1_top_n}  stage1_min_score={cfg.stage1_min_score}\n"
        f"  fault handler ON (segfault stack dumps to this terminal)\n"
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
