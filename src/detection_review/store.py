from __future__ import annotations

import json
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Mapping

from detection_review.workload import compute_workload

Status = Literal["initial", "confirmed", "incorrect"]
INITIAL: Status = "initial"
CONFIRMED: Status = "confirmed"
INCORRECT: Status = "incorrect"
EXPORTED_STATES = frozenset({CONFIRMED})


def _utc_now() -> str:
    """Naive UTC timestamp.

    Timestamps are kept naive-UTC to avoid timezone-object construction
    issues seen on some native-library stacks.
    """
    return datetime.utcnow().isoformat()


def _parse_utc(value: str) -> datetime:
    """Parse ``_utc_now()`` or older aware ISO strings without building tzinfo."""
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1]
    if len(text) >= 6 and text[-6] in "+-" and text[-3] == ":":
        text = text[:-6]
    elif len(text) >= 5 and text[-5] in "+-" and text[-3] != ":":
        text = text[:-5]
    return datetime.fromisoformat(text)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def normalize_status(status: str | None) -> Status:
    if status in (CONFIRMED, "relabeled"):
        return CONFIRMED
    if status in (INCORRECT, "ignored", "rejected"):
        return INCORRECT
    return INITIAL


def _crash_trace(message: str) -> None:
    print(f"CRASHTRACE: {message}", flush=True)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def _resolve_image(images_dir: Path, file_name: str) -> Path:
    direct = images_dir / file_name
    if direct.is_file():
        return direct
    base = images_dir / Path(file_name).name
    if base.is_file():
        return base
    raise FileNotFoundError(f"Image not found: {file_name} under {images_dir}")


@dataclass
class DetectionRecord:
    id: int
    image_id: int
    category_id: int
    bbox: list[float]  # COCO xywh pixels
    label: str
    status: Status = INITIAL
    source: str = "prediction"
    score: float | None = None
    area: float | None = None
    iscrowd: int = 0
    source_annotation_id: int | None = None
    source_point_id: int | None = None
    source_label_id: int | None = None
    original_bbox: list[float] | None = None
    flagged_for_review: bool = False

    @property
    def review_state(self) -> Status:
        return normalize_status(self.status)

    @property
    def is_confirmed(self) -> bool:
        return self.review_state == CONFIRMED

    @property
    def is_incorrect(self) -> bool:
        return self.review_state == INCORRECT

    @property
    def is_initial(self) -> bool:
        return self.review_state == INITIAL

    def geometry_changed(self, *, eps: float = 0.5) -> bool:
        if self.original_bbox is None or len(self.original_bbox) != len(self.bbox):
            return False
        return any(abs(float(a) - float(b)) > eps for a, b in zip(self.bbox, self.original_bbox))

    def label_changed(self) -> bool:
        if self.source_label_id is None:
            return False
        return int(self.category_id) != int(self.source_label_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "image_id": self.image_id,
            "category_id": self.category_id,
            "bbox": [float(x) for x in self.bbox],
            "label": self.label,
            "status": self.review_state,
            "source": self.source,
            "score": self.score,
            "area": self.area,
            "iscrowd": self.iscrowd,
            "source_annotation_id": self.source_annotation_id,
            "source_point_id": self.source_point_id,
            "source_label_id": self.source_label_id,
            "original_bbox": (
                [float(x) for x in self.original_bbox] if self.original_bbox is not None else None
            ),
            "flagged_for_review": bool(self.flagged_for_review),
        }

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, Any],
        *,
        cat_id_to_name: dict[int, str] | None = None,
        cat_name_to_id: dict[str, int] | None = None,
    ) -> "DetectionRecord":
        cid = _optional_int(raw.get("category_id"))
        label = str(raw.get("label") or "")
        if cid is None and label and cat_name_to_id:
            cid = cat_name_to_id.get(label)
        if cid is None:
            cid = 0
        if not label and cat_id_to_name:
            label = cat_id_to_name.get(cid, str(cid))
        return cls(
            id=int(raw["id"]),
            image_id=int(raw["image_id"]),
            category_id=int(cid),
            bbox=[float(x) for x in raw["bbox"]],
            label=label or str(cid),
            status=normalize_status(raw.get("status")),
            source=str(raw.get("source") or "prediction"),
            score=float(raw["score"]) if raw.get("score") is not None else None,
            area=float(raw["area"]) if raw.get("area") is not None else None,
            iscrowd=int(raw.get("iscrowd") or 0),
            source_annotation_id=_optional_int(raw.get("source_annotation_id")),
            source_point_id=_optional_int(raw.get("source_point_id")),
            source_label_id=_optional_int(raw.get("source_label_id")),
            original_bbox=(
                [float(x) for x in raw["original_bbox"]]
                if isinstance(raw.get("original_bbox"), list)
                else None
            ),
            flagged_for_review=_as_bool(raw.get("flagged_for_review")),
        )

    def to_coco_ann(self, ann_id: int) -> dict[str, Any]:
        x, y, w, h = self.bbox
        out = {
            "id": ann_id,
            "image_id": self.image_id,
            "category_id": self.category_id,
            "bbox": [float(x), float(y), float(w), float(h)],
            "area": float(self.area if self.area is not None else max(w, 0) * max(h, 0)),
            "iscrowd": int(self.iscrowd),
        }
        if self.score is not None:
            out["score"] = float(self.score)
        if self.source_annotation_id is not None:
            out["source_annotation_id"] = int(self.source_annotation_id)
        if self.source_point_id is not None:
            out["source_point_id"] = int(self.source_point_id)
        if self.source_label_id is not None:
            out["source_label_id"] = int(self.source_label_id)
        if self.flagged_for_review:
            out["flagged_for_review"] = True
        return out


@dataclass
class RemovedSourceRef:
    """Source ids for a detection removed from the local store."""

    source_annotation_id: int
    source_point_id: int | None = None
    image_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_annotation_id": int(self.source_annotation_id),
            "source_point_id": self.source_point_id,
            "image_id": self.image_id,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "RemovedSourceRef | None":
        if not isinstance(raw, dict):
            return None
        ann_id = _optional_int(raw.get("source_annotation_id") or raw.get("annotation_id"))
        if ann_id is None:
            return None
        return cls(
            source_annotation_id=ann_id,
            source_point_id=_optional_int(raw.get("source_point_id") or raw.get("point_id")),
            image_id=_optional_int(raw.get("image_id")),
        )


@dataclass
class ReviewStore:
    """In-memory reviewed detections backed by prediction COCO."""

    dataset_id: str
    images_dir: Path
    categories: list[dict[str, Any]]
    images: list[dict[str, Any]]
    detections: dict[int, DetectionRecord]
    cat_id_to_name: dict[int, str]
    cat_name_to_id: dict[str, int]
    image_id_to_meta: dict[int, dict[str, Any]]
    image_ids_ordered: list[int]
    next_det_id: int
    filter_info: dict[str, Any] = field(default_factory=dict)
    removed: list[RemovedSourceRef] = field(default_factory=list)
    counts: dict[str, int] = field(
        default_factory=lambda: {
            "confirmed": 0,
            "incorrect": 0,
            "unreviewed": 0,
            "added": 0,
            "resized": 0,
            "deleted": 0,
        }
    )

    @classmethod
    def from_predictions(
        cls,
        dataset_id: str,
        images_dir: Path,
        predictions_path: Path,
        *,
        top_n: int = 100,
        min_score: float = 0.05,
    ) -> "ReviewStore":
        _crash_trace(f"from_predictions read {predictions_path}")
        coco = json.loads(predictions_path.read_text())
        _crash_trace(
            f"from_predictions parsed json: "
            f"{len(coco.get('images') or [])} images, "
            f"{len(coco.get('annotations') or [])} anns"
        )
        categories = list(coco.get("categories") or [])
        if not categories:
            raise ValueError("predictions COCO has no categories")
        cat_id_to_name = {int(c["id"]): str(c["name"]) for c in categories}
        cat_name_to_id = {str(c["name"]): int(c["id"]) for c in categories}
        images = list(coco.get("images") or [])
        image_id_to_meta = {int(im["id"]): im for im in images}

        raw_anns = list(coco.get("annotations") or [])
        has_scores = any(
            ann.get("score") is not None or ann.get("confidence") is not None for ann in raw_anns
        )
        score_min = min_score if has_scores else -1.0
        n_keep = max(1, int(top_n)) if has_scores else 10**9
        per_image: dict[int, list[tuple[float, dict[str, Any]]]] = {}
        after_score = 0
        for ann in raw_anns:
            score = ann.get("score")
            if score is None:
                score = ann.get("confidence")
            score_f = float(score) if score is not None else 1.0
            if has_scores and score_f <= score_min:
                continue
            after_score += 1
            image_id = int(ann["image_id"])
            per_image.setdefault(image_id, []).append((score_f, ann))

        kept: list[tuple[float, dict[str, Any]]] = []
        for image_id in sorted(per_image.keys()):
            scored = per_image[image_id]
            scored.sort(key=lambda t: (-t[0], int(t[1]["id"])))
            kept.extend(scored[:n_keep])

        detections: dict[int, DetectionRecord] = {}
        max_id = 0
        for score_f, ann in kept:
            aid = int(ann["id"])
            max_id = max(max_id, aid)
            cid = int(ann["category_id"])
            bbox = [float(x) for x in ann["bbox"]]
            detections[aid] = DetectionRecord(
                id=aid,
                image_id=int(ann["image_id"]),
                category_id=cid,
                bbox=bbox,
                label=cat_id_to_name.get(cid, str(cid)),
                status=INITIAL,
                source="prediction",
                score=score_f if has_scores else None,
                area=float(ann["area"]) if "area" in ann else None,
                iscrowd=int(ann.get("iscrowd", 0)),
                source_annotation_id=_optional_int(ann.get("source_annotation_id")),
                source_point_id=_optional_int(ann.get("source_point_id")),
                source_label_id=_optional_int(ann.get("source_label_id")),
                original_bbox=list(bbox),
            )
        for ann in raw_anns:
            max_id = max(max_id, int(ann["id"]))

        _crash_trace(f"from_predictions building store with {len(detections)} detections")
        store = cls(
            dataset_id=dataset_id,
            images_dir=images_dir,
            categories=categories,
            images=images,
            detections=detections,
            cat_id_to_name=cat_id_to_name,
            cat_name_to_id=cat_name_to_id,
            image_id_to_meta=image_id_to_meta,
            image_ids_ordered=[int(im["id"]) for im in images],
            next_det_id=max_id + 1,
            filter_info={
                "top_n": top_n if has_scores else None,
                "top_n_scope": "per_image" if has_scores else "all",
                "min_score": min_score if has_scores else None,
                "raw_annotations": len(raw_anns),
                "after_score_filter": after_score,
                "images_with_detections": len(per_image),
                "loaded": len(detections),
            },
            counts={
                "confirmed": 0,
                "incorrect": 0,
                "unreviewed": len(detections),
                "added": 0,
                "resized": 0,
                "deleted": 0,
            },
        )
        _crash_trace("from_predictions store ready")
        return store

    def image_path(self, image_id: int) -> Path:
        meta = self.image_id_to_meta[image_id]
        return _resolve_image(self.images_dir, meta["file_name"])

    def is_kept(self, det: DetectionRecord) -> bool:
        """True if the detection is exported (confirmed only)."""
        return det.review_state in EXPORTED_STATES

    def score_extent(self) -> dict[str, float]:
        scores = [d.score for d in self.detections.values() if d.score is not None]
        if not scores:
            return {"min": 0.0, "max": 1.0}
        return {"min": float(min(scores)), "max": float(max(scores))}

    def list_patches(
        self,
        *,
        page: int = 1,
        page_size: int = 48,
        status: str | None = None,
        label: str | None = None,
        include_confirmed: bool = True,
        include_incorrect: bool = True,
        include_initial: bool = True,
        min_prob: float | None = None,
        max_prob: float | None = None,
        flagged_only: bool = False,
    ) -> dict[str, Any]:
        items = []
        for det in self.detections.values():
            if det.is_confirmed and not include_confirmed:
                continue
            if det.is_incorrect and not include_incorrect:
                continue
            if det.is_initial and not include_initial:
                continue
            if flagged_only and not det.flagged_for_review:
                continue
            if status and det.review_state != normalize_status(status):
                continue
            if label and det.label != label:
                continue
            score = det.score if det.score is not None else 1.0
            if min_prob is not None and score < min_prob:
                continue
            if max_prob is not None and score > max_prob:
                continue
            items.append(det)
        image_rank = {iid: i for i, iid in enumerate(self.image_ids_ordered)}
        items.sort(
            key=lambda d: (
                image_rank.get(d.image_id, 10**9),
                float(d.bbox[1]) if d.bbox else 0.0,
                float(d.bbox[0]) if d.bbox else 0.0,
                d.id,
            )
        )
        total = len(items)
        page = max(1, page)
        start = (page - 1) * page_size
        end = start + page_size
        slice_ = items[start:end]
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
            "filter": dict(self.filter_info),
            "score_extent": self.score_extent(),
            "counts": dict(self.counts),
            "items": [
                {
                    "id": d.id,
                    "image_id": d.image_id,
                    "label": d.label,
                    "category_id": d.category_id,
                    "status": d.review_state,
                    "score": d.score,
                    "bbox": d.bbox,
                    "flagged_for_review": bool(d.flagged_for_review),
                    "thumb_url": (
                        f"/api/patches/{d.id}/thumb"
                        f"?x={d.bbox[0]:.1f}&y={d.bbox[1]:.1f}"
                        f"&w={d.bbox[2]:.1f}&h={d.bbox[3]:.1f}"
                    ),
                }
                for d in slice_
            ],
        }

    def get_context(self, det_id: int) -> dict[str, Any]:
        det = self.detections[det_id]
        meta = self.image_id_to_meta[det.image_id]
        boxes = []
        for d in self.detections.values():
            if d.image_id != det.image_id:
                continue
            boxes.append(
                {
                    "id": d.id,
                    "label": d.label,
                    "category_id": d.category_id,
                    "status": d.review_state,
                    "bbox": d.bbox,
                    "flagged_for_review": bool(d.flagged_for_review),
                    "focused": d.id == det_id,
                }
            )
        boxes.sort(key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0]), int(b["id"])))
        return {
            "detection_id": det_id,
            "image_id": det.image_id,
            "file_name": meta["file_name"],
            "width": meta.get("width"),
            "height": meta.get("height"),
            "image_url": f"/api/images/{det.image_id}/file",
            "focused": {
                "id": det.id,
                "label": det.label,
                "category_id": det.category_id,
                "status": det.review_state,
                "bbox": det.bbox,
                "flagged_for_review": bool(det.flagged_for_review),
            },
            "boxes": boxes,
        }

    def _leave_status(self, det: DetectionRecord) -> None:
        state = det.review_state
        if state == CONFIRMED:
            self.counts["confirmed"] = max(0, self.counts["confirmed"] - 1)
        elif state == INCORRECT:
            self.counts["incorrect"] = max(0, self.counts["incorrect"] - 1)
        else:
            self.counts["unreviewed"] = max(0, self.counts.get("unreviewed", 0) - 1)

    def _set_status(self, det: DetectionRecord, status: Status) -> bool:
        if det.review_state == status:
            det.status = status
            return False
        self._leave_status(det)
        det.status = status
        if status == CONFIRMED:
            self.counts["confirmed"] += 1
        elif status == INCORRECT:
            self.counts["incorrect"] += 1
        else:
            self.counts["unreviewed"] = self.counts.get("unreviewed", 0) + 1
        return True

    def confirm(self, det_ids: list[int]) -> int:
        n = 0
        for did in det_ids:
            if self._set_status(self.detections[did], CONFIRMED):
                n += 1
        return n

    def ignore(self, det_ids: list[int]) -> int:
        n = 0
        for did in det_ids:
            if self._set_status(self.detections[did], INCORRECT):
                n += 1
        return n

    def relabel(self, det_ids: list[int], label: str) -> int:
        if label not in self.cat_name_to_id:
            raise ValueError(f"Unknown label: {label}")
        dets = [self.detections[did] for did in det_ids]
        if dets and all(det.label == label for det in dets):
            raise ValueError(f'Already class "{label}". Choose a different class.')
        cid = self.cat_name_to_id[label]
        n = 0
        for det in dets:
            label_changed = det.label != label
            if label_changed:
                det.label = label
                det.category_id = cid
            status_changed = self._set_status(det, CONFIRMED)
            if label_changed or status_changed:
                n += 1
        return n

    def clear(self, det_ids: list[int]) -> int:
        n = 0
        for did in det_ids:
            if self._set_status(self.detections[did], INITIAL):
                n += 1
        return n

    def set_flagged(self, det_ids: list[int], flagged: bool) -> int:
        n = 0
        want = bool(flagged)
        for did in det_ids:
            det = self.detections[did]
            if det.flagged_for_review == want:
                continue
            det.flagged_for_review = want
            n += 1
        return n

    def list_images(self) -> list[dict[str, Any]]:
        out = []
        for iid in self.image_ids_ordered:
            meta = self.image_id_to_meta[iid]
            n_active = sum(
                1
                for d in self.detections.values()
                if d.image_id == iid and self.is_kept(d)
            )
            out.append(
                {
                    "id": iid,
                    "file_name": meta["file_name"],
                    "width": meta.get("width"),
                    "height": meta.get("height"),
                    "n_boxes": n_active,
                    "fn_reviewed": bool(meta.get("_fn_reviewed", False)),
                    "image_url": f"/api/images/{iid}/file?max_edge=3200",
                }
            )
        return out

    def get_image_detail(self, image_id: int) -> dict[str, Any]:
        meta = self.image_id_to_meta[image_id]
        boxes = [
            {
                "id": d.id,
                "label": d.label,
                "category_id": d.category_id,
                "status": d.review_state,
                "bbox": d.bbox,
                "source": d.source,
                "score": d.score,
                "flagged_for_review": bool(d.flagged_for_review),
            }
            for d in self.detections.values()
            if d.image_id == image_id
        ]
        boxes.sort(key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0]), int(b["id"])))
        return {
            "id": image_id,
            "file_name": meta["file_name"],
            "width": meta.get("width"),
            "height": meta.get("height"),
            "fn_reviewed": bool(meta.get("_fn_reviewed", False)),
            "image_url": f"/api/images/{image_id}/file?max_edge=3200",
            "boxes": boxes,
        }

    def add_detection(
        self,
        image_id: int,
        bbox: list[float],
        label: str,
        *,
        flagged_for_review: bool = False,
    ) -> DetectionRecord:
        if label not in self.cat_name_to_id:
            raise ValueError(f"Unknown label: {label}")
        if image_id not in self.image_id_to_meta:
            raise KeyError(f"Unknown image_id: {image_id}")
        x, y, w, h = [float(v) for v in bbox]
        if w <= 1 or h <= 1:
            raise ValueError("bbox too small")
        det = DetectionRecord(
            id=self.next_det_id,
            image_id=image_id,
            category_id=self.cat_name_to_id[label],
            bbox=[x, y, w, h],
            label=label,
            status=CONFIRMED,
            source="fn_review",
            flagged_for_review=bool(flagged_for_review),
        )
        self.next_det_id += 1
        self.detections[det.id] = det
        self.counts["added"] += 1
        self.counts["confirmed"] += 1
        return det

    def update_detection(
        self,
        det_id: int,
        *,
        bbox: list[float] | None = None,
        label: str | None = None,
    ) -> DetectionRecord:
        det = self.detections[det_id]
        if bbox is not None:
            det.bbox = [float(v) for v in bbox]
            self.counts["resized"] += 1
        if label is not None:
            if label not in self.cat_name_to_id:
                raise ValueError(f"Unknown label: {label}")
            det.label = label
            det.category_id = self.cat_name_to_id[label]
            self._set_status(det, CONFIRMED)
        return det

    def _tombstone(self, det: DetectionRecord) -> None:
        if det.source_annotation_id is None:
            return
        existing = {ref.source_annotation_id for ref in self.removed}
        if det.source_annotation_id in existing:
            return
        self.removed.append(
            RemovedSourceRef(
                source_annotation_id=int(det.source_annotation_id),
                source_point_id=det.source_point_id,
                image_id=det.image_id,
            )
        )

    def delete_detections(self, det_ids: list[int]) -> int:
        n = 0
        for did in det_ids:
            key = int(did)
            if key not in self.detections:
                continue
            self.delete_detection(key)
            n += 1
        return n

    def delete_detection(self, det_id: int) -> None:
        det = self.detections[det_id]
        if self.is_kept(det):
            self.counts["deleted"] += 1
        self._leave_status(det)
        self._tombstone(det)
        del self.detections[det_id]

    def mark_image_done(self, image_id: int, done: bool = True) -> None:
        self.image_id_to_meta[image_id]["_fn_reviewed"] = done

    def fn_reviewed_image_ids(self) -> list[int]:
        return [
            int(iid)
            for iid, meta in self.image_id_to_meta.items()
            if meta.get("_fn_reviewed")
        ]

    def recompute_status_counts(self) -> None:
        confirmed = incorrect = unreviewed = added = 0
        for det in self.detections.values():
            if det.source == "fn_review":
                added += 1
            if det.is_confirmed:
                confirmed += 1
            elif det.is_incorrect:
                incorrect += 1
            else:
                unreviewed += 1
        self.counts["confirmed"] = confirmed
        self.counts["incorrect"] = incorrect
        self.counts["unreviewed"] = unreviewed
        self.counts["added"] = added

    def export_review_state(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "next_det_id": self.next_det_id,
            "counts": dict(self.counts),
            "fn_reviewed_image_ids": self.fn_reviewed_image_ids(),
            "detections": [
                det.to_dict()
                for det in sorted(self.detections.values(), key=lambda d: (d.image_id, d.id))
            ],
            "removed": [ref.to_dict() for ref in self.removed],
        }

    def apply_review_state(self, payload: dict[str, Any]) -> None:
        detections: dict[int, DetectionRecord] = {}
        max_id = 0
        for raw in payload.get("detections") or []:
            det = DetectionRecord.from_dict(
                raw,
                cat_id_to_name=self.cat_id_to_name,
                cat_name_to_id=self.cat_name_to_id,
            )
            detections[det.id] = det
            max_id = max(max_id, det.id)
        self.detections = detections
        self.next_det_id = max(int(payload.get("next_det_id") or 0), max_id + 1)
        for meta in self.image_id_to_meta.values():
            meta["_fn_reviewed"] = False
        for iid in payload.get("fn_reviewed_image_ids") or []:
            if int(iid) in self.image_id_to_meta:
                self.image_id_to_meta[int(iid)]["_fn_reviewed"] = True
        saved_counts = payload.get("counts") or {}
        self.recompute_status_counts()
        for key in ("resized", "deleted"):
            if key in saved_counts:
                self.counts[key] = int(saved_counts[key] or 0)
        self.removed = []
        seen: set[int] = set()
        for raw in payload.get("removed") or []:
            ref = RemovedSourceRef.from_dict(raw)
            if ref is None or ref.source_annotation_id in seen:
                continue
            seen.add(ref.source_annotation_id)
            self.removed.append(ref)

    def apply_overlay(self, overlay: list[dict[str, Any]]) -> None:
        overlay_by_id = {int(item["id"]): item for item in overlay}
        for did in list(self.detections):
            if did not in overlay_by_id:
                self._tombstone(self.detections[did])
                del self.detections[did]
        for item in overlay:
            did = int(item["id"])
            label = str(item.get("label") or "")
            cid = self.cat_name_to_id.get(label)
            if did in self.detections:
                det = self.detections[did]
                det.bbox = [float(x) for x in item["bbox"]]
                if label:
                    det.label = label
                    if cid is not None:
                        det.category_id = cid
                det.status = normalize_status(item.get("status"))
                if item.get("source"):
                    det.source = str(item["source"])
                if "flagged_for_review" in item:
                    det.flagged_for_review = _as_bool(item.get("flagged_for_review"))
            else:
                self.detections[did] = DetectionRecord(
                    id=did,
                    image_id=int(item["image_id"]),
                    category_id=int(cid if cid is not None else 0),
                    bbox=[float(x) for x in item["bbox"]],
                    label=label or str(cid or 0),
                    status=normalize_status(item.get("status")),
                    source=str(item.get("source") or "fn_review"),
                    flagged_for_review=_as_bool(item.get("flagged_for_review")),
                )
        if self.detections:
            self.next_det_id = max(self.next_det_id, max(self.detections) + 1)
        self.recompute_status_counts()

    def export_review_overlay(self) -> list[dict[str, Any]]:
        """All detections with review status, including ignored and untouched."""
        out = []
        for det in sorted(self.detections.values(), key=lambda d: (d.image_id, d.id)):
            meta = self.image_id_to_meta.get(det.image_id) or {}
            out.append(
                {
                    "id": det.id,
                    "image_id": det.image_id,
                    "file_name": Path(meta.get("file_name") or "").name,
                    "label": det.label,
                    "bbox": [float(x) for x in det.bbox],
                    "status": det.review_state,
                    "source": det.source,
                    "flagged_for_review": bool(det.flagged_for_review),
                }
            )
        return out

    def write_review_overlay(self, path: Path) -> Path:
        write_json_atomic(path, self.export_review_overlay())
        return path

    def export_coco(self) -> dict[str, Any]:
        anns = []
        ann_id = 1
        for det in sorted(self.detections.values(), key=lambda d: (d.image_id, d.id)):
            if not self.is_kept(det):
                continue
            anns.append(det.to_coco_ann(ann_id))
            ann_id += 1
        images = []
        for im in self.images:
            images.append(
                {
                    "id": im["id"],
                    "file_name": Path(im["file_name"]).name,
                    "width": im.get("width"),
                    "height": im.get("height"),
                }
            )
        return {
            "info": {"description": f"reviewed:{self.dataset_id}", "year": datetime.now().year},
            "licenses": [],
            "categories": deepcopy(self.categories),
            "images": images,
            "annotations": anns,
        }

    def write_coco(self, path: Path) -> Path:
        write_json_atomic(path, self.export_coco())
        return path


@dataclass
class StageTiming:
    intervals: list[dict[str, str]] = field(default_factory=list)
    open_start: str | None = None

    def start(self) -> None:
        if self.open_start is not None:
            return
        self.open_start = _utc_now()

    def stop(self) -> float:
        if self.open_start is None:
            return self.elapsed_sec()
        end = _utc_now()
        self.intervals.append({"started_at": self.open_start, "stopped_at": end})
        self.open_start = None
        return self.elapsed_sec()

    @property
    def running(self) -> bool:
        return self.open_start is not None

    def closed_elapsed_sec(self) -> float:
        total = 0.0
        for iv in self.intervals:
            t0 = _parse_utc(iv["started_at"])
            t1 = _parse_utc(iv["stopped_at"])
            total += (t1 - t0).total_seconds()
        return total

    def elapsed_sec(self) -> float:
        total = self.closed_elapsed_sec()
        if self.open_start is not None:
            t0 = _parse_utc(self.open_start)
            total += (datetime.utcnow() - t0).total_seconds()
        return total

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "elapsed_sec": round(self.elapsed_sec(), 3),
            "elapsed_closed_sec": round(self.closed_elapsed_sec(), 3),
            "intervals": list(self.intervals),
            "open_start": self.open_start,
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any] | None,
        *,
        close_open: bool = True,
        closed_at: str | None = None,
    ) -> "StageTiming":
        timing = cls()
        payload = data or {}
        timing.intervals = [dict(iv) for iv in payload.get("intervals") or []]
        open_start = payload.get("open_start")
        if not open_start:
            return timing
        if close_open:
            stop = closed_at or _utc_now()
            last = timing.intervals[-1] if timing.intervals else None
            if not last or last.get("started_at") != open_start or last.get("stopped_at") != stop:
                timing.intervals.append({"started_at": open_start, "stopped_at": stop})
            return timing
        timing.open_start = str(open_start)
        return timing


@dataclass
class DatasetRun:
    study_id: str
    tester: str
    dataset_id: str
    run_dir: Path
    store: ReviewStore
    stage1: StageTiming = field(default_factory=StageTiming)
    stage2: StageTiming = field(default_factory=StageTiming)
    completed: bool = False
    gt_comparison: dict[str, Any] | None = None

    def require_stage_running(self, stage: Literal["stage1", "stage2"]) -> None:
        if self.completed:
            return
        timing = self.stage1 if stage == "stage1" else self.stage2
        if not timing.running:
            raise RuntimeError(f"{stage} timer is not running — press Start first")

    def require_review_running(self) -> None:
        if self.completed:
            return
        if not self.stage1.running and not self.stage2.running:
            raise RuntimeError("timer is not running — press Start first")

    def pause_other_stage(self, active: Literal["stage1", "stage2"]) -> bool:
        other = self.stage2 if active == "stage1" else self.stage1
        if not other.running:
            return False
        other.stop()
        return True

    def reviewed_coco_path(self) -> Path:
        return self.run_dir / "annotations" / "instances_reviewed.json"

    def review_overlay_path(self) -> Path:
        return self.run_dir / "annotations" / "review_overlay.json"

    def review_state_path(self) -> Path:
        return self.run_dir / "review_state.json"

    def reviewed_state_snapshot_path(self) -> Path:
        return self.run_dir / "reviewed" / "review_state.json"

    def final_coco_path(self) -> Path:
        return self.run_dir / "annotations" / "instances_final.json"

    def final_overlay_path(self) -> Path:
        return self.run_dir / "annotations" / "review_overlay_final.json"

    def final_review_state_path(self) -> Path:
        return self.run_dir / "final" / "review_state.json"

    def timing_path(self) -> Path:
        return self.run_dir / "timing.json"

    def freeze_reviewed_snapshot(self) -> Path:
        path = self.reviewed_state_snapshot_path()
        write_json_atomic(path, self.store.export_review_state())
        return path

    def write_timing(self, *, write_store: bool = True) -> Path:
        _crash_trace(f"write_timing mkdir {self.run_dir}")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.timing_path()
        existing: dict[str, Any] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError, TypeError):
                loaded = None
            if isinstance(loaded, dict):
                existing = loaded

        coco_rel = existing.get("reviewed_coco") or "annotations/instances_reviewed.json"
        overlay_rel = existing.get("review_overlay") or "annotations/review_overlay.json"
        state_rel = existing.get("review_state") or "review_state.json"
        final_coco_rel = existing.get("final_coco")
        final_overlay_rel = existing.get("final_overlay")
        final_state_rel = existing.get("final_review_state")
        reviewed_counts = existing.get("reviewed_counts")
        post_review_updated_at = existing.get("post_review_updated_at")

        if write_store:
            if self.completed:
                _crash_trace("write_timing write_final")
                coco_path = self.store.write_coco(self.final_coco_path())
                overlay_path = self.store.write_review_overlay(self.final_overlay_path())
                state_path = self.final_review_state_path()
                write_json_atomic(state_path, self.store.export_review_state())
                final_coco_rel = str(coco_path.relative_to(self.run_dir))
                final_overlay_rel = str(overlay_path.relative_to(self.run_dir))
                final_state_rel = str(state_path.relative_to(self.run_dir))
                post_review_updated_at = _utc_now()
            else:
                _crash_trace("write_timing write_coco")
                coco_path = self.store.write_coco(self.reviewed_coco_path())
                _crash_trace("write_timing write_overlay")
                overlay_path = self.store.write_review_overlay(self.review_overlay_path())
                state_path = self.review_state_path()
                _crash_trace("write_timing export_review_state")
                write_json_atomic(state_path, self.store.export_review_state())
                coco_rel = str(coco_path.relative_to(self.run_dir))
                overlay_rel = str(overlay_path.relative_to(self.run_dir))
                state_rel = str(state_path.relative_to(self.run_dir))

        if not self.completed or reviewed_counts is None:
            reviewed_counts = dict(self.store.counts)
        workload_counts = reviewed_counts if self.completed else self.store.counts

        _crash_trace("write_timing build payload (_utc_now / stage.to_dict)")
        payload = {
            "study_id": self.study_id,
            "tester": self.tester,
            "dataset_id": self.dataset_id,
            "completed": self.completed,
            "updated_at": _utc_now(),
            "reviewed_coco": coco_rel,
            "review_overlay": overlay_rel,
            "review_state": state_rel,
            "reviewed_counts": dict(reviewed_counts),
            "stage1": self.stage1.to_dict(),
            "stage2": self.stage2.to_dict(),
            "counts": dict(self.store.counts),
            "n_images": len(self.store.images),
            "fn_reviewed_image_ids": self.store.fn_reviewed_image_ids(),
            "gt_comparison": self.gt_comparison,
            "workload": compute_workload(
                t1_sec=self.stage1.elapsed_sec(),
                t2_sec=self.stage2.elapsed_sec(),
                counts=workload_counts,
                n_images=len(self.store.images),
                gt_fn=(self.gt_comparison or {}).get("fn")
                if isinstance(self.gt_comparison, dict)
                else None,
            ),
        }
        if final_coco_rel:
            payload["final_coco"] = final_coco_rel
            payload["final_overlay"] = final_overlay_rel
            payload["final_review_state"] = final_state_rel
            payload["post_review_updated_at"] = post_review_updated_at
        _crash_trace(f"write_timing write {path.name}")
        write_json_atomic(path, payload)
        _crash_trace("write_timing done")
        return path

    @classmethod
    def load(
        cls,
        run_dir: Path,
        *,
        images_dir: Path,
        predictions_path: Path,
        top_n: int = 100,
        min_score: float = 0.05,
        close_open_timers: bool = True,
    ) -> "DatasetRun":
        run_dir = run_dir.resolve()
        timing_path = run_dir / "timing.json"
        if not timing_path.is_file():
            raise FileNotFoundError(f"timing.json not found in {run_dir}")
        timing = json.loads(timing_path.read_text())
        store = ReviewStore.from_predictions(
            str(timing.get("dataset_id") or run_dir.name),
            images_dir,
            predictions_path,
            top_n=top_n,
            min_score=min_score,
        )
        final_state = run_dir / "final" / "review_state.json"
        reviewed_snap = run_dir / "reviewed" / "review_state.json"
        state_path = run_dir / "review_state.json"
        overlay_path = run_dir / "annotations" / "review_overlay.json"
        if final_state.is_file():
            store.apply_review_state(json.loads(final_state.read_text()))
        elif state_path.is_file():
            store.apply_review_state(json.loads(state_path.read_text()))
        elif reviewed_snap.is_file():
            store.apply_review_state(json.loads(reviewed_snap.read_text()))
        elif overlay_path.is_file():
            store.apply_overlay(json.loads(overlay_path.read_text()))
            saved_counts = timing.get("counts") or {}
            for key in ("resized", "deleted"):
                if key in saved_counts:
                    store.counts[key] = int(saved_counts[key] or 0)
        for iid in timing.get("fn_reviewed_image_ids") or []:
            if int(iid) in store.image_id_to_meta:
                store.image_id_to_meta[int(iid)]["_fn_reviewed"] = True
        updated_at = timing.get("updated_at")
        return cls(
            study_id=str(timing.get("study_id") or ""),
            tester=str(timing.get("tester") or ""),
            dataset_id=str(timing.get("dataset_id") or store.dataset_id),
            run_dir=run_dir,
            store=store,
            stage1=StageTiming.from_dict(
                timing.get("stage1"),
                close_open=close_open_timers,
                closed_at=updated_at,
            ),
            stage2=StageTiming.from_dict(
                timing.get("stage2"),
                close_open=close_open_timers,
                closed_at=updated_at,
            ),
            completed=bool(timing.get("completed")),
            gt_comparison=timing.get("gt_comparison"),
        )

    def export(self) -> dict[str, str]:
        timing_path = self.write_timing()
        return {
            "coco": str(self.reviewed_coco_path()),
            "overlay": str(self.review_overlay_path()),
            "timing": str(timing_path),
        }


def new_run_dir(data_root: Path, study_id: str, tester: str, dataset_id: str) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%S")
    short = uuid.uuid4().hex[:8]
    return data_root / "review_runs" / study_id / tester / f"{dataset_id}_{stamp}_{short}"
