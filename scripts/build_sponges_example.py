#!/usr/bin/env python3
"""Build the committed Sponges example under ``examples/sponges/``.

This is a maintainer script: it converts two internal episode packages
(100 query images each) into the small, self-contained example shipped in
this repository. It is not needed to *use* the example — see the README.

Each input package directory must contain::

    <package>/support.json          # shared support/exemplar COCO
    <package>/test_gt.json          # ground truth for the slice
    <package>/sam3_work/predictions_coco.json

Query images are never copied (they are downloaded separately; see the
README). Support images are the exemplar crops themselves: each support
annotation is cropped out of its original image and saved as its own
image, with the annotation bbox rewritten to cover the whole crop
(``[0, 0, width, height]``). This keeps `support.json` self-consistent at
any resolution — no rescaling of bbox coordinates is ever needed — and
is exactly the crop the Stage 1 class-example panel displays.

Usage (paths are examples; adjust to your checkouts)::

    python scripts/build_sponges_example.py \
      --slice sponges_0_100=/path/to/package_a \
      --slice sponges_200_300=/path/to/package_b \
      --support-images-source /path/to/exemplar_images \
      --images-dir /path/to/downloaded/query_images
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

KEEP_PRED_FIELDS = ("id", "image_id", "category_id", "bbox", "area", "iscrowd", "score")
KEEP_GT_FIELDS = ("id", "image_id", "category_id", "bbox", "area", "iscrowd")


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a COCO dict")
    return data


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n")


def _basename_images(coco: dict[str, Any]) -> list[dict[str, Any]]:
    images = []
    for im in coco.get("images") or []:
        out = {"id": im["id"], "file_name": Path(str(im["file_name"])).name}
        for key in ("width", "height"):
            if im.get(key) is not None:
                out[key] = im[key]
        images.append(out)
    return images


def _clean(coco: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    anns = []
    for ann in coco.get("annotations") or []:
        out = {k: ann[k] for k in fields if k in ann}
        if "bbox" in out:
            out["bbox"] = [round(float(x), 2) for x in out["bbox"]]
        if out.get("area") is not None:
            out["area"] = round(float(out["area"]), 2)
        if out.get("score") is not None:
            out["score"] = round(float(out["score"]), 4)
        anns.append(out)
    return {
        "images": _basename_images(coco),
        "annotations": anns,
        "categories": [
            {"id": c["id"], "name": c["name"]} for c in coco.get("categories") or []
        ],
    }


def _write_exemplar_crop(src: Path, bbox: list[float], dst: Path) -> tuple[int, int]:
    """Crop ``bbox`` (original-image pixels) out of ``src``; return (w, h)."""
    x, y, w, h = [float(v) for v in bbox]
    with Image.open(src) as im:
        im = im.convert("RGB")
        width, height = im.size
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(width, int(x + w))
        y1 = min(height, int(y + h))
        if x1 <= x0 or y1 <= y0:
            raise SystemExit(f"empty exemplar crop for {src} bbox={bbox}")
        crop = im.crop((x0, y0, x1, y1))
        dst.parent.mkdir(parents=True, exist_ok=True)
        crop.save(dst, "JPEG", quality=88)
        return crop.size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--slice",
        action="append",
        required=True,
        metavar="DATASET_ID=PACKAGE_DIR",
        help="Slice to include; repeat for each slice (first slice provides support)",
    )
    parser.add_argument("--support-images-source", type=Path, required=True)
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=None,
        help="Downloaded query-image directory; when given, every referenced "
        "query image is verified to exist there by file name",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "examples" / "sponges",
    )
    args = parser.parse_args()

    slices: list[tuple[str, Path]] = []
    for item in args.slice:
        if "=" not in item:
            raise SystemExit(f"--slice must be DATASET_ID=PACKAGE_DIR, got {item!r}")
        dataset_id, pkg = item.split("=", 1)
        slices.append((dataset_id.strip(), Path(pkg.strip())))

    out: Path = args.out
    datasets: list[dict[str, Any]] = []
    shared_categories: list[dict[str, Any]] | None = None

    for index, (dataset_id, pkg) in enumerate(slices):
        predictions = _clean(_load(pkg / "sam3_work" / "predictions_coco.json"), KEEP_PRED_FIELDS)
        ground_truth = _clean(_load(pkg / "test_gt.json"), KEEP_GT_FIELDS)
        if shared_categories is None:
            shared_categories = predictions["categories"]
        for name, coco in (("predictions", predictions), ("ground_truth", ground_truth)):
            if coco["categories"] != shared_categories:
                raise SystemExit(f"{pkg} {name}: categories do not match the first slice")
        slice_name = dataset_id.removeprefix("sponges_")
        _write(out / f"slice_{slice_name}" / "predictions.json", predictions)
        _write(out / f"slice_{slice_name}" / "ground_truth.json", ground_truth)

        if args.images_dir is not None:
            missing = [
                im["file_name"]
                for im in predictions["images"]
                if not (args.images_dir / im["file_name"]).is_file()
            ]
            if missing:
                raise SystemExit(
                    f"{dataset_id}: {len(missing)} query images missing from "
                    f"{args.images_dir} (first: {missing[0]})"
                )
        datasets.append(
            {
                "id": dataset_id,
                "images_dir": "../../../SAM3-FSOD/datasets/utas_sponges_20054/images",
                "predictions_coco": f"slice_{slice_name}/predictions.json",
                "support_coco": "support.json",
                "support_images_dir": "support_images",
                "ground_truth_coco": f"slice_{slice_name}/ground_truth.json",
            }
        )
        print(
            f"{dataset_id}: {len(predictions['images'])} images, "
            f"{len(predictions['annotations'])} predictions, "
            f"{len(ground_truth['annotations'])} ground-truth boxes"
        )

    first_pkg = slices[0][1]
    raw_support = _load(first_pkg / "support.json")
    if [
        {"id": c["id"], "name": c["name"]} for c in raw_support.get("categories") or []
    ] != shared_categories:
        raise SystemExit("support categories do not match slice categories")
    # One image per annotation: the crop itself. The rewritten annotation
    # bbox covers the whole crop, so support.json stays self-consistent
    # regardless of the original image resolution.
    shutil.rmtree(out / "support_images", ignore_errors=True)
    raw_images = {int(im["id"]): im for im in raw_support.get("images") or []}
    support_images: list[dict[str, Any]] = []
    support_anns: list[dict[str, Any]] = []
    for ann in sorted(raw_support.get("annotations") or [], key=lambda a: int(a["id"])):
        raw_im = raw_images.get(int(ann["image_id"]))
        if raw_im is None:
            raise SystemExit(f"support annotation {ann['id']} has no image")
        src = args.support_images_source / Path(str(raw_im["file_name"])).name
        if not src.is_file():
            raise SystemExit(f"support image not found: {src}")
        crop_name = f"ann{int(ann['id'])}__{src.name}"
        crop_w, crop_h = _write_exemplar_crop(
            src, ann["bbox"], out / "support_images" / crop_name
        )
        new_image_id = len(support_images) + 1
        support_images.append(
            {"id": new_image_id, "file_name": crop_name, "width": crop_w, "height": crop_h}
        )
        support_anns.append(
            {
                "id": int(ann["id"]),
                "image_id": new_image_id,
                "category_id": int(ann["category_id"]),
                "bbox": [0, 0, crop_w, crop_h],
                "area": crop_w * crop_h,
                "iscrowd": int(ann.get("iscrowd") or 0),
            }
        )
    _write(
        out / "support.json",
        {
            "images": support_images,
            "annotations": support_anns,
            "categories": shared_categories,
        },
    )
    print(f"support: {len(support_images)} exemplar crops, {len(support_anns)} boxes")

    _write(out / "manifest.json", {"study_id": "sponges_example", "datasets": datasets})
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
