"""Review workload from Stage 1 / Stage 2 timers.

Measured workload is ``W = T1 + T2``. Unit costs are seconds per Stage 1
decision (confirm or ignore a model box) and seconds of Stage 2 search per
image. Stage 2 additions are not counted as Stage 1 decisions.
"""

from __future__ import annotations

from typing import Any, Mapping


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _fmt_sec(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}s"


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}×"


def stage1_decision_count(counts: Mapping[str, Any] | None) -> int:
    """Model boxes the tester confirmed or ignored (excludes Stage 2 adds)."""
    data = counts or {}
    confirmed = _as_int(data.get("confirmed"))
    added = _as_int(data.get("added"))
    ignored = _as_int(data.get("incorrect"))
    return max(0, confirmed - added) + max(0, ignored)


def compute_workload(
    *,
    t1_sec: float | None,
    t2_sec: float | None,
    counts: Mapping[str, Any] | None,
    n_images: int | None,
    gt_fn: int | None = None,
) -> dict[str, Any]:
    """Derive workload stats for persistence and the results page."""
    t1 = _as_float(t1_sec)
    t2 = _as_float(t2_sec)
    if t1 is None:
        t1 = 0.0
    if t2 is None:
        t2 = 0.0
    data = counts or {}
    n_added = max(0, _as_int(data.get("added")))
    n_ignored = max(0, _as_int(data.get("incorrect")))
    n_unreviewed = max(0, _as_int(data.get("unreviewed")))
    n_s1 = stage1_decision_count(data)
    n_confirmed_model = max(0, _as_int(data.get("confirmed")) - n_added)
    images = _as_int(n_images, default=0)
    if images < 0:
        images = 0

    w_sec = t1 + t2
    beta = (t1 / n_s1) if n_s1 > 0 else None
    alpha_img = (t2 / images) if images > 0 else None
    alpha_fn = (t2 / n_added) if n_added > 0 else None
    rho = (alpha_img / beta) if beta and alpha_img is not None and beta > 0 else None
    stage1_share = (t1 / w_sec) if w_sec > 0 else None
    gt_fn_n = _as_int(gt_fn) if gt_fn is not None else None

    gt_line = None
    if gt_fn_n is not None:
        gt_line = (
            f"Stage 2 added {n_added} box{'es' if n_added != 1 else ''}. "
            f"Ground truth still has {gt_fn_n} unmatched (FN)."
        )

    payload = {
        "w_sec": _round(w_sec),
        "t1_sec": _round(t1),
        "t2_sec": _round(t2),
        "n_s1": n_s1,
        "n_confirmed_model": n_confirmed_model,
        "n_ignored": n_ignored,
        "n_added": n_added,
        "n_unreviewed": n_unreviewed,
        "n_images": images,
        "beta_s_per_decision": _round(beta),
        "alpha_s_per_image": _round(alpha_img),
        "alpha_s_per_fn": _round(alpha_fn),
        "rho": _round(rho),
        "stage1_share": _round(stage1_share, 4),
        "gt_fn": gt_fn_n,
        "display": {
            "w": _fmt_sec(_round(w_sec, 1)),
            "t1": _fmt_sec(_round(t1, 1)),
            "t2": _fmt_sec(_round(t2, 1)),
            "beta": (
                f"{beta:.1f}s / decision"
                if beta is not None
                else "—"
            ),
            "alpha_img": (
                f"{alpha_img:.1f}s / image"
                if alpha_img is not None
                else "—"
            ),
            "alpha_fn": (
                f"{alpha_fn:.1f}s / miss"
                if alpha_fn is not None
                else "—"
            ),
            "rho": _fmt_ratio(rho),
            "n_s1": str(n_s1),
            "n_images": str(images),
            "n_added": str(n_added),
            "gt_line": gt_line,
        },
    }
    return payload


def workload_from_timing(
    timing: Mapping[str, Any] | None,
    *,
    gt_fn: int | None = None,
) -> dict[str, Any]:
    """Build workload from a ``timing.json`` payload (and optional GT FN count)."""
    data = dict(timing or {})
    stage1 = data.get("stage1") or {}
    stage2 = data.get("stage2") or {}
    counts = data.get("counts") or {}
    n_images = data.get("n_images")
    if gt_fn is None:
        gt = data.get("gt_comparison")
        if isinstance(gt, dict) and gt.get("fn") is not None:
            gt_fn = _as_int(gt.get("fn"))
    return compute_workload(
        t1_sec=_as_float(stage1.get("elapsed_sec")),
        t2_sec=_as_float(stage2.get("elapsed_sec")),
        counts=counts,
        n_images=_as_int(n_images) if n_images is not None else None,
        gt_fn=gt_fn,
    )
