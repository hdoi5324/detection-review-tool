from __future__ import annotations

import bisect
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

# COCO defaults: AP over IoU 0.50:0.05:0.95, 101-point recall, max 100 dets/image.
IOU_THRS = [round(0.5 + i * 0.05, 2) for i in range(10)]
REC_THRS = [i / 100.0 for i in range(101)]
MAX_DETS = 100


def _basename(file_name: str) -> str:
    return Path(file_name).name


def _images_by_name(coco: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {_basename(im["file_name"]): im for im in coco.get("images") or []}


def _anns_by_image_id(coco: dict[str, Any]) -> dict[int, list]:
    out: dict[int, list] = defaultdict(list)
    for ann in coco.get("annotations") or []:
        out[int(ann["image_id"])].append(ann)
    return out


def coco_relpaths(coco: dict[str, Any]) -> dict[str, str]:
    """Map image basename -> original COCO file_name (may include subdirs)."""
    return {_basename(im["file_name"]): im["file_name"] for im in coco.get("images") or []}


def _cat_names(coco: dict[str, Any]) -> dict[int, str]:
    return {int(c["id"]): str(c["name"]) for c in coco.get("categories") or []}


def image_file_rank(coco: dict[str, Any]) -> dict[str, int]:
    """Basename -> index in coco['images'] (same sequence Stage 1 uses)."""
    rank: dict[str, int] = {}
    for i, im in enumerate(coco.get("images") or []):
        name = _basename(im.get("file_name") or "")
        if name and name not in rank:
            rank[name] = i
    return rank


def image_order_key(
    item: dict[str, Any],
    *,
    file_rank: dict[str, int] | None = None,
) -> tuple:
    """Sort boxes in dataset image order, then top-to-bottom, left-to-right."""
    bbox = item.get("bbox") or [0.0, 0.0]
    y = float(bbox[1]) if len(bbox) > 1 else 0.0
    x = float(bbox[0]) if bbox else 0.0
    iid = int(item.get("id") or 0)
    if file_rank is None:
        return (y, x, iid)
    fname = _basename(str(item.get("file_name") or ""))
    return (file_rank.get(fname, 10**9), y, x, iid)


def _iou(a: list[float], b: list[float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix0, iy0 = max(ax, bx), max(ay, by)
    ix1, iy1 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _box_label(box: dict[str, Any]) -> str:
    return str(box.get("label") or "")


def _greedy_iou_match(
    gt_boxes: list[dict[str, Any]],
    det_boxes: list[dict[str, Any]],
    iou_thresh: float,
    *,
    det_indices: list[int] | None = None,
) -> list[tuple[int, int, float]]:
    """1-1 same-class match: pairs with IoU ≥ thresh, highest IoU first.

    Each GT and each detection is used at most once. When several GT boxes
    overlap the same detection (or vice versa), the higher-IoU pair wins.
    """
    if det_indices is None:
        det_indices = list(range(len(det_boxes)))
    pairs: list[tuple[float, int, int]] = []
    for i, g in enumerate(gt_boxes):
        g_name = _box_label(g)
        gb = g.get("bbox") or [0.0, 0.0, 0.0, 0.0]
        for j in det_indices:
            d = det_boxes[j]
            if _box_label(d) != g_name:
                continue
            iou = _iou(gb, d["bbox"])
            if iou >= iou_thresh:
                pairs.append((iou, i, j))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
    used_g: set[int] = set()
    used_d: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for iou, i, j in pairs:
        if i in used_g or j in used_d:
            continue
        used_g.add(i)
        used_d.add(j)
        matches.append((i, j, iou))
    return matches


def _best_iou_same_class(
    box: dict[str, Any],
    others: list[dict[str, Any]],
    indices: list[int] | None = None,
) -> float:
    name = _box_label(box)
    bb = box.get("bbox") or [0.0, 0.0, 0.0, 0.0]
    best = 0.0
    if indices is None:
        indices = range(len(others))
    for j in indices:
        other = others[j]
        if _box_label(other) != name:
            continue
        iou = _iou(bb, other["bbox"])
        if iou > best:
            best = iou
    return best


def compare_to_gt(
    reviewed_coco: dict[str, Any],
    gt_path: Path,
    iou_thresh: float = 0.5,
) -> dict[str, Any]:
    gt = json.loads(gt_path.read_text())
    gt_cats = _cat_names(gt)
    rev_cats = _cat_names(reviewed_coco)

    # Match by file_name then evaluate per image
    gt_images = _images_by_name(gt)
    rev_images = _images_by_name(reviewed_coco)
    gt_anns_by_img = _anns_by_image_id(gt)
    rev_anns_by_img = _anns_by_image_id(reviewed_coco)

    tp = fp = fn = 0
    per_class = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "gt": 0})
    false_negatives: list[dict[str, Any]] = []

    for fname, gt_im in gt_images.items():
        rev_im = rev_images.get(fname)
        gt_list = list(gt_anns_by_img.get(int(gt_im["id"]), []))
        rev_list = list(rev_anns_by_img.get(int(rev_im["id"]), [])) if rev_im else []

        gt_boxes = [
            {
                "label": gt_cats.get(int(g["category_id"]), str(g["category_id"])),
                "bbox": g["bbox"],
                "ann": g,
            }
            for g in gt_list
        ]
        rev_boxes = [
            {
                "label": rev_cats.get(int(r["category_id"]), str(r["category_id"])),
                "bbox": r["bbox"],
            }
            for r in rev_list
        ]
        matches = _greedy_iou_match(gt_boxes, rev_boxes, iou_thresh)
        matched_gt = {i for i, _, _ in matches}
        matched_rev = {j for _, j, _ in matches}

        for i, gbox in enumerate(gt_boxes):
            g_name = gbox["label"]
            per_class[g_name]["gt"] += 1
            if i in matched_gt:
                tp += 1
                per_class[g_name]["tp"] += 1
                continue
            fn += 1
            per_class[g_name]["fn"] += 1
            g = gbox["ann"]
            false_negatives.append(
                {
                    "id": len(false_negatives) + 1,
                    "file_name": gt_im.get("file_name") or fname,
                    "gt_ann_id": int(g["id"]),
                    "gt_image_id": int(gt_im["id"]),
                    "rev_image_id": int(rev_im["id"]) if rev_im else None,
                    "label": g_name,
                    "bbox": [float(x) for x in g["bbox"]],
                    "width": gt_im.get("width"),
                    "height": gt_im.get("height"),
                    "best_iou": round(_best_iou_same_class(gbox, rev_boxes), 4),
                }
            )

        for j, rbox in enumerate(rev_boxes):
            if j in matched_rev:
                continue
            fp += 1
            per_class[rbox["label"]]["fp"] += 1

    file_rank = image_file_rank(reviewed_coco)
    next_rank = max(file_rank.values(), default=-1) + 1
    for im in gt.get("images") or []:
        name = _basename(im.get("file_name") or "")
        if name and name not in file_rank:
            file_rank[name] = next_rank
            next_rank += 1
    false_negatives.sort(key=lambda fn: image_order_key(fn, file_rank=file_rank))

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    coco = coco_detection_metrics(reviewed_coco, gt)
    return {
        "iou_thresh": iou_thresh,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "ap": coco["ap"],
        "ap50": coco["ap50"],
        "ar100": coco["ar100"],
        "per_class": dict(per_class),
        "false_negatives": false_negatives,
    }


def comparison_metrics(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Copy a compare_to_gt payload without the FN thumbnail list."""
    if not payload:
        return None
    return {k: v for k, v in payload.items() if k != "false_negatives"}


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def _fmt_metric(value: float | None, integer: bool) -> str:
    if value is None:
        return "—"
    if integer:
        return str(int(round(value)))
    return f"{value:.4f}"


def _fmt_delta(delta: float | None, integer: bool) -> str:
    if delta is None:
        return "—"
    if integer:
        n = int(round(delta))
        return "0" if n == 0 else f"{n:+d}"
    if abs(delta) < 5e-5:
        return "0.0000"
    return f"{delta:+.4f}"


def _delta_class(delta: float | None, higher_better: bool, integer: bool) -> str:
    if delta is None:
        return "flat"
    eps = 0.5 if integer else 5e-5
    if abs(delta) < eps:
        return "flat"
    good = delta > 0 if higher_better else delta < 0
    return "up" if good else "down"


_OVERALL_METRICS = (
    ("precision", "Precision", True, False),
    ("recall", "Recall", True, False),
    ("f1", "F1", True, False),
    ("tp", "True positives", True, True),
    ("fp", "False positives", False, True),
    ("fn", "False negatives", False, True),
    ("ap", "AP", True, False),
    ("ap50", "AP50", True, False),
    ("ar100", "AR@100", True, False),
)


def metric_table_rows(
    original: dict[str, Any] | None,
    reviewed: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    orig = original or {}
    rev = reviewed or {}
    rows = []
    for key, label, higher_better, integer in _OVERALL_METRICS:
        o = orig.get(key)
        r = rev.get(key)
        o_n = float(o) if isinstance(o, (int, float)) else None
        r_n = float(r) if isinstance(r, (int, float)) else None
        delta = None if o_n is None or r_n is None else r_n - o_n
        rows.append(
            {
                "label": label,
                "original": _fmt_metric(o_n, integer),
                "reviewed": _fmt_metric(r_n, integer),
                "delta": _fmt_delta(delta, integer),
                "delta_class": _delta_class(delta, higher_better, integer),
            }
        )
    return rows


def class_metric_rows(
    original: dict[str, Any] | None,
    reviewed: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    orig_pc = (original or {}).get("per_class") or {}
    rev_pc = (reviewed or {}).get("per_class") or {}
    names = sorted(set(orig_pc) | set(rev_pc), key=str.lower)
    rows = []
    for name in names:
        o = orig_pc.get(name) or {}
        r = rev_pc.get(name) or {}
        otp, ofp, ofn = int(o.get("tp") or 0), int(o.get("fp") or 0), int(o.get("fn") or 0)
        rtp, rfp, rfn = int(r.get("tp") or 0), int(r.get("fp") or 0), int(r.get("fn") or 0)
        if "gt" in r:
            gt_n = int(r.get("gt") or 0)
        elif "gt" in o:
            gt_n = int(o.get("gt") or 0)
        else:
            gt_n = rtp + rfn if (rtp + rfn) else otp + ofn
        _, _, of1 = _prf(otp, ofp, ofn)
        _, _, rf1 = _prf(rtp, rfp, rfn)
        d_f1 = rf1 - of1
        d_tp, d_fp, d_fn = rtp - otp, rfp - ofp, rfn - ofn
        rows.append(
            {
                "label": name,
                "gt_count": gt_n,
                "original_f1": _fmt_metric(of1, False),
                "reviewed_f1": _fmt_metric(rf1, False),
                "delta_f1": _fmt_delta(d_f1, False),
                "delta_f1_class": _delta_class(d_f1, True, False),
                "original_counts": f"{otp} / {ofp} / {ofn}",
                "reviewed_counts": f"{rtp} / {rfp} / {rfn}",
                "delta_tp": _fmt_delta(float(d_tp), True),
                "delta_fp": _fmt_delta(float(d_fp), True),
                "delta_fn": _fmt_delta(float(d_fn), True),
                "delta_tp_class": _delta_class(float(d_tp), True, True),
                "delta_fp_class": _delta_class(float(d_fp), False, True),
                "delta_fn_class": _delta_class(float(d_fn), False, True),
            }
        )
    return rows


def _ann_score(ann: dict[str, Any]) -> float:
    score = ann.get("score")
    if score is None:
        score = ann.get("confidence")
    return float(score) if score is not None else 1.0


def _align_dets_to_gt(
    reviewed_coco: dict[str, Any],
    gt: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Map reviewed anns onto GT image/category ids (by file name and class name)."""
    gt_cats = _cat_names(gt)
    rev_cats = _cat_names(reviewed_coco)
    gt_name_to_id = {name: cid for cid, name in gt_cats.items()}
    gt_images = _images_by_name(gt)
    rev_to_gt_image: dict[int, int] = {}
    for fname, rim in _images_by_name(reviewed_coco).items():
        gim = gt_images.get(fname)
        if gim is not None:
            rev_to_gt_image[int(rim["id"])] = int(gim["id"])

    gts: list[dict[str, Any]] = []
    for ann in gt.get("annotations") or []:
        name = gt_cats.get(int(ann["category_id"]), str(ann["category_id"]))
        gts.append(
            {
                "id": int(ann["id"]),
                "image_id": int(ann["image_id"]),
                "category": name,
                "bbox": [float(x) for x in ann["bbox"]],
                "iscrowd": int(ann.get("iscrowd", 0)),
            }
        )

    dets: list[dict[str, Any]] = []
    for ann in reviewed_coco.get("annotations") or []:
        gt_im_id = rev_to_gt_image.get(int(ann["image_id"]))
        if gt_im_id is None:
            continue
        name = rev_cats.get(int(ann["category_id"]), str(ann["category_id"]))
        if name not in gt_name_to_id:
            continue
        dets.append(
            {
                "id": int(ann["id"]),
                "image_id": gt_im_id,
                "category": name,
                "bbox": [float(x) for x in ann["bbox"]],
                "score": _ann_score(ann),
            }
        )

    classes = sorted({g["category"] for g in gts})
    return gts, dets, classes


def _interpolated_ap(tp_flags: list[bool], n_gt: int) -> float:
    if n_gt <= 0:
        return 0.0
    nd = len(tp_flags)
    if nd == 0:
        return 0.0
    tp_cum = 0
    fp_cum = 0
    recalls: list[float] = []
    precisions: list[float] = []
    for is_tp in tp_flags:
        if is_tp:
            tp_cum += 1
        else:
            fp_cum += 1
        recalls.append(tp_cum / n_gt)
        precisions.append(tp_cum / (tp_cum + fp_cum))
    for i in range(nd - 2, -1, -1):
        if precisions[i] < precisions[i + 1]:
            precisions[i] = precisions[i + 1]
    ap = 0.0
    for rt in REC_THRS:
        idx = bisect.bisect_left(recalls, rt)
        if idx < nd:
            ap += precisions[idx]
    return ap / len(REC_THRS)


def _match_class(
    class_gts: list[dict[str, Any]],
    class_dets: list[dict[str, Any]],
    iou_thr: float,
    max_dets: int = MAX_DETS,
) -> tuple[list[bool], int, float]:
    """Greedy match. Returns (tp flags in score order, n_gt, recall)."""
    n_gt = sum(1 for g in class_gts if not g["iscrowd"])
    gts_by_img: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for g in class_gts:
        gts_by_img[g["image_id"]].append(g)

    dets_by_img: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for d in class_dets:
        dets_by_img[d["image_id"]].append(d)

    kept: list[dict[str, Any]] = []
    for img_id, img_dets in dets_by_img.items():
        img_dets.sort(key=lambda d: (-d["score"], d["id"]))
        kept.extend(img_dets[:max_dets])
    kept.sort(key=lambda d: (-d["score"], d["image_id"], d["id"]))

    used: set[int] = set()
    tp_flags: list[bool] = []
    for det in kept:
        candidates = gts_by_img.get(det["image_id"]) or []
        best_gt = None
        best_iou = 0.0
        best_crowd = None
        best_crowd_iou = 0.0
        for g in candidates:
            iou = _iou(det["bbox"], g["bbox"])
            if g["iscrowd"]:
                if iou > best_crowd_iou:
                    best_crowd_iou, best_crowd = iou, g
                continue
            if g["id"] in used:
                continue
            if iou > best_iou:
                best_iou, best_gt = iou, g
        if best_gt is not None and best_iou >= iou_thr:
            used.add(best_gt["id"])
            tp_flags.append(True)
        elif best_crowd is not None and best_crowd_iou >= iou_thr:
            continue
        else:
            tp_flags.append(False)

    recall = (sum(1 for f in tp_flags if f) / n_gt) if n_gt else 0.0
    return tp_flags, n_gt, recall


def coco_detection_metrics(
    reviewed_coco: dict[str, Any],
    gt: dict[str, Any],
    *,
    max_dets: int = MAX_DETS,
) -> dict[str, float]:
    """COCO-style AP (0.50:0.95), AP50, and AR@100, mean over GT classes."""
    gts, dets, classes = _align_dets_to_gt(reviewed_coco, gt)
    gts_by_cls: dict[str, list] = defaultdict(list)
    dets_by_cls: dict[str, list] = defaultdict(list)
    for g in gts:
        gts_by_cls[g["category"]].append(g)
    for d in dets:
        dets_by_cls[d["category"]].append(d)

    aps: list[float] = []
    ap50s: list[float] = []
    ars: list[float] = []
    for name in classes:
        class_gts = gts_by_cls.get(name) or []
        n_gt = sum(1 for g in class_gts if not g["iscrowd"])
        if n_gt == 0:
            continue
        class_dets = dets_by_cls.get(name) or []
        class_aps: list[float] = []
        class_ars: list[float] = []
        for thr in IOU_THRS:
            tp_flags, _, recall = _match_class(class_gts, class_dets, thr, max_dets=max_dets)
            ap_t = _interpolated_ap(tp_flags, n_gt)
            class_aps.append(ap_t)
            class_ars.append(recall)
            if abs(thr - 0.5) < 1e-9:
                ap50s.append(ap_t)
        aps.append(sum(class_aps) / len(class_aps))
        ars.append(sum(class_ars) / len(class_ars))

    def mean(xs: list[float]) -> float:
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    return {"ap": mean(aps), "ap50": mean(ap50s), "ar100": mean(ars)}


def _tag_tp_fp_fn(
    gt_boxes: list[dict[str, Any]],
    det_boxes: list[dict[str, Any]],
    iou_thresh: float,
) -> None:
    """Same 1-1 class+IoU match as compare_to_gt. Only confirmed detections can be TP."""
    confirmed = [j for j, d in enumerate(det_boxes) if d.get("status") == "confirmed"]
    matched_gt: set[int] = set()
    for i, j, iou in _greedy_iou_match(gt_boxes, det_boxes, iou_thresh, det_indices=confirmed):
        matched_gt.add(i)
        gt_boxes[i]["eval"] = "tp"
        gt_boxes[i]["iou"] = iou
        det_boxes[j]["eval"] = "tp"
        det_boxes[j]["iou"] = iou
    for i, g in enumerate(gt_boxes):
        if i in matched_gt:
            continue
        g["eval"] = "fn"
        best = _best_iou_same_class(g, det_boxes, confirmed)
        if best > 0:
            g["iou"] = best
    for d in det_boxes:
        if d.get("eval"):
            continue
        if d.get("status") == "confirmed":
            d["eval"] = "fp"
            best = _best_iou_same_class(d, gt_boxes)
            if best > 0:
                d["iou"] = best
        elif d.get("status") == "incorrect":
            d["eval"] = "ignore"
        else:
            d["eval"] = "clear"


def overlay_for_image(
    reviewed_coco: dict[str, Any],
    gt: dict[str, Any],
    file_name: str,
    *,
    focused_gt_ann_id: int | None = None,
    review_dets: list[dict[str, Any]] | None = None,
    iou_thresh: float = 0.5,
) -> dict[str, Any]:
    """GT boxes plus tester detections (all statuses) for one image, matched by file name."""
    fname = _basename(file_name)
    gt_im = _images_by_name(gt).get(fname)
    rev_im = _images_by_name(reviewed_coco).get(fname)
    if gt_im is None and rev_im is None and not review_dets:
        raise KeyError(f"Unknown image: {fname}")

    gt_cats = _cat_names(gt)
    rev_cats = _cat_names(reviewed_coco)
    meta = gt_im or rev_im or {}
    gt_anns = _anns_by_image_id(gt) if gt_im is not None else {}
    rev_anns = _anns_by_image_id(reviewed_coco) if rev_im is not None else {}
    gt_boxes = []
    if gt_im is not None:
        for ann in gt_anns.get(int(gt_im["id"]), []):
            gt_boxes.append(
                {
                    "id": int(ann["id"]),
                    "kind": "gt",
                    "label": gt_cats.get(int(ann["category_id"]), str(ann["category_id"])),
                    "bbox": [float(x) for x in ann["bbox"]],
                    "focused": focused_gt_ann_id is not None and int(ann["id"]) == int(focused_gt_ann_id),
                }
            )
    reviewed_boxes = []
    if review_dets is not None:
        for det in review_dets:
            if _basename(str(det.get("file_name") or "")) != fname:
                continue
            reviewed_boxes.append(
                {
                    "id": int(det["id"]),
                    "kind": "detection",
                    "label": det.get("label") or "",
                    "bbox": [float(x) for x in det["bbox"]],
                    "status": det.get("status") or "initial",
                    "source": det.get("source"),
                }
            )
    elif rev_im is not None:
        for ann in rev_anns.get(int(rev_im["id"]), []):
            reviewed_boxes.append(
                {
                    "id": int(ann["id"]),
                    "kind": "detection",
                    "label": rev_cats.get(int(ann["category_id"]), str(ann["category_id"])),
                    "bbox": [float(x) for x in ann["bbox"]],
                    "status": "confirmed",
                }
            )
    _tag_tp_fp_fn(gt_boxes, reviewed_boxes, iou_thresh)
    gt_boxes.sort(key=image_order_key)
    reviewed_boxes.sort(key=image_order_key)
    return {
        "file_name": fname,
        "width": meta.get("width"),
        "height": meta.get("height"),
        "gt_boxes": gt_boxes,
        "reviewed_boxes": reviewed_boxes,
        "focused_gt_ann_id": focused_gt_ann_id,
        "iou_thresh": iou_thresh,
    }
