from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from detection_review.store import _utc_now, write_json_atomic
from detection_review.workload import compute_workload

RESUME_STAGES = frozenset({"stage1", "stage2", "results", "done"})


def tester_dir(data_root: Path, study_id: str, tester: str) -> Path:
    return data_root / "review_runs" / study_id / tester


def session_path(data_root: Path, study_id: str, tester: str) -> Path:
    return tester_dir(data_root, study_id, tester) / "session.json"


@dataclass
class SessionProgress:
    study_id: str
    tester: str
    dataset_index: int = 0
    stage: str = "stage1"
    current_run_dir: str | None = None
    last_completed_run_dir: str | None = None
    stage1_page: int = 1
    stage1_page_size: int = 48
    stage2_image_id: int | None = None
    stage1_tour_seen: bool = False
    stage2_tour_seen: bool = False
    final_review: bool = False
    updated_at: str | None = None

    def cursor(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "stage1_page": self.stage1_page,
            "stage1_page_size": self.stage1_page_size,
            "stage2_image_id": self.stage2_image_id,
            "stage1_tour_seen": self.stage1_tour_seen,
            "stage2_tour_seen": self.stage2_tour_seen,
        }

    def resolve_current_run(self, data_root: Path) -> Path | None:
        return _resolve_run_dir(data_root, self.study_id, self.tester, self.current_run_dir)

    def resolve_last_completed(self, data_root: Path) -> Path | None:
        return _resolve_run_dir(
            data_root, self.study_id, self.tester, self.last_completed_run_dir
        )


def _resolve_run_dir(
    data_root: Path, study_id: str, tester: str, name: str | None
) -> Path | None:
    if not name:
        return None
    path = Path(name)
    if not path.is_absolute():
        path = tester_dir(data_root, study_id, tester) / name
    if path.is_dir() and (path / "timing.json").is_file():
        return path.resolve()
    return None


def load_session_progress(data_root: Path, study_id: str, tester: str) -> SessionProgress | None:
    path = session_path(data_root, study_id, tester)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    stage = str(raw.get("stage") or "stage1")
    if stage not in RESUME_STAGES:
        stage = "stage1"
    page_size = int(raw.get("stage1_page_size") or 48)
    if page_size not in (24, 48, 96):
        page_size = 48
    image_id = raw.get("stage2_image_id")
    return SessionProgress(
        study_id=str(raw.get("study_id") or study_id),
        tester=str(raw.get("tester") or tester),
        dataset_index=max(0, int(raw.get("dataset_index") or 0)),
        stage=stage,
        current_run_dir=raw.get("current_run_dir"),
        last_completed_run_dir=raw.get("last_completed_run_dir"),
        stage1_page=max(1, int(raw.get("stage1_page") or 1)),
        stage1_page_size=page_size,
        stage2_image_id=int(image_id) if image_id is not None and image_id != "" else None,
        stage1_tour_seen=bool(raw.get("stage1_tour_seen")),
        stage2_tour_seen=bool(raw.get("stage2_tour_seen")),
        final_review=bool(raw.get("final_review")),
        updated_at=raw.get("updated_at"),
    )


def save_session_progress(data_root: Path, progress: SessionProgress) -> Path:
    progress.updated_at = _utc_now()
    path = session_path(data_root, progress.study_id, progress.tester)
    payload = asdict(progress)
    write_json_atomic(path, payload)
    return path


def _timing_sort_key(timing: dict[str, Any], run_dir: Path) -> str:
    return str(timing.get("updated_at") or "") or str(run_dir.stat().st_mtime)


def _iter_run_timings(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    out: list[tuple[Path, dict[str, Any]]] = []
    if not root.is_dir():
        return out
    for child in root.iterdir():
        if not child.is_dir():
            continue
        timing_path = child / "timing.json"
        if not timing_path.is_file():
            continue
        try:
            timing = json.loads(timing_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(timing, dict):
            continue
        out.append((child.resolve(), timing))
    return out


def _infer_stage(timing: dict[str, Any]) -> str:
    if timing.get("completed"):
        return "results"
    fn_ids = timing.get("fn_reviewed_image_ids") or []
    stage2 = timing.get("stage2") or {}
    if fn_ids or stage2.get("intervals") or (stage2.get("elapsed_closed_sec") or 0) > 0:
        return "stage2"
    return "stage1"


def infer_session_progress(
    data_root: Path,
    study_id: str,
    tester: str,
    dataset_ids: list[str],
) -> SessionProgress:
    progress = SessionProgress(study_id=study_id, tester=tester)
    runs = _iter_run_timings(tester_dir(data_root, study_id, tester))
    if not runs or not dataset_ids:
        return progress
    by_dataset: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for run_dir, timing in runs:
        ds = str(timing.get("dataset_id") or "")
        if not ds:
            continue
        by_dataset.setdefault(ds, []).append((run_dir, timing))

    last_completed: Path | None = None
    for i, ds_id in enumerate(dataset_ids):
        entries = by_dataset.get(ds_id) or []
        if not entries:
            progress.dataset_index = i
            progress.stage = "stage1"
            return progress
        latest_dir, latest = max(entries, key=lambda item: _timing_sort_key(item[1], item[0]))
        if latest.get("completed"):
            last_completed = latest_dir
            progress.last_completed_run_dir = latest_dir.name
            progress.dataset_index = i + 1
            progress.stage = "results"
            progress.current_run_dir = None
            continue
        progress.dataset_index = i
        progress.stage = _infer_stage(latest)
        progress.current_run_dir = latest_dir.name
        progress.last_completed_run_dir = last_completed.name if last_completed else None
        return progress

    progress.stage = "done"
    progress.current_run_dir = None
    return progress


def _load_json_any(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _dataset_results_view(
    *,
    coco_path: Path,
    overlay_path: Path,
    gt: Any,
    counts: Mapping[str, Any],
) -> dict[str, Any]:
    coco = _load_json_any(coco_path)
    if not isinstance(coco, dict):
        coco = {}
    overlay = _load_json_any(overlay_path)
    if not isinstance(overlay, list):
        overlay = []
    categories = [
        {"id": c["id"], "name": c["name"]} for c in coco.get("categories") or []
    ]
    return {
        "gt": gt if isinstance(gt, dict) else None,
        "counts": dict(counts or {}),
        "review_dets": overlay,
        "exported": {
            "coco": str(coco_path) if coco_path.is_file() else "",
            "overlay": str(overlay_path) if overlay_path.is_file() else "",
        },
        "categories": categories,
    }


def load_completed_results(run_dir: Path) -> dict[str, Any] | None:
    timing_path = run_dir / "timing.json"
    if not timing_path.is_file():
        return None
    try:
        timing = json.loads(timing_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    reviewed_overlay = run_dir / "annotations" / "review_overlay.json"
    reviewed_coco = run_dir / "annotations" / "instances_reviewed.json"
    final_overlay = run_dir / "annotations" / "review_overlay_final.json"
    final_coco = run_dir / "annotations" / "instances_final.json"
    final_state = run_dir / "final" / "review_state.json"
    has_qaqc = final_coco.is_file() or final_overlay.is_file() or final_state.is_file()

    timed_gt = _load_json_any(run_dir / "gt_comparison.json")
    if not isinstance(timed_gt, dict):
        timed_gt = timing.get("gt_comparison") if isinstance(timing.get("gt_comparison"), dict) else None
    qaqc_gt = _load_json_any(run_dir / "gt_comparison_final.json")
    if not isinstance(qaqc_gt, dict):
        qaqc_gt = timed_gt
    gt_original = _load_json_any(run_dir / "gt_original.json")
    if not isinstance(gt_original, dict):
        gt_original = None

    timed_counts = timing.get("reviewed_counts") or timing.get("counts") or {}
    qaqc_counts = dict(timed_counts)
    if has_qaqc:
        state = _load_json_any(final_state)
        if isinstance(state, dict) and isinstance(state.get("counts"), dict):
            qaqc_counts = state["counts"]
        elif isinstance(timing.get("counts"), dict):
            qaqc_counts = timing["counts"]

    timed_view = _dataset_results_view(
        coco_path=reviewed_coco,
        overlay_path=reviewed_overlay,
        gt=timed_gt,
        counts=timed_counts,
    )
    qaqc_view = (
        _dataset_results_view(
            coco_path=final_coco if final_coco.is_file() else reviewed_coco,
            overlay_path=final_overlay if final_overlay.is_file() else reviewed_overlay,
            gt=qaqc_gt,
            counts=qaqc_counts,
        )
        if has_qaqc
        else None
    )
    default = qaqc_view if qaqc_view is not None else timed_view
    n_images = timing.get("n_images")
    if n_images is None:
        default_coco = _load_json_any(Path(default["exported"]["coco"])) if default["exported"]["coco"] else {}
        n_images = len((default_coco or {}).get("images") or [])
    timed_gt_fn = timed_view["gt"].get("fn") if isinstance(timed_view.get("gt"), dict) else None
    stage1 = timing.get("stage1") or {}
    stage2 = timing.get("stage2") or {}
    workload = compute_workload(
        t1_sec=stage1.get("elapsed_sec"),
        t2_sec=stage2.get("elapsed_sec"),
        counts=timed_counts,
        n_images=n_images,
        gt_fn=timed_gt_fn if timed_gt_fn is not None else None,
    )
    return {
        "gt": default["gt"],
        "gt_original": gt_original,
        "counts": default["counts"],
        "n_images": n_images,
        "timing": {
            "stage1": stage1,
            "stage2": stage2,
        },
        "workload": workload,
        "dataset_id": timing.get("dataset_id"),
        "has_qaqc": has_qaqc,
        "results_source": "qaqc" if has_qaqc else "timed",
        "exported": {
            **default["exported"],
            "timing": str(timing_path),
        },
        "review_dets": default["review_dets"],
        "categories": default["categories"],
        "views": {
            "timed": timed_view,
            "qaqc": qaqc_view,
        },
    }
