from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Compile templates before native modules (e.g. PIL) are imported; on some
# stacks Jinja ``_compile`` can segfault after those load, so warm the cache first.
PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
TEMPLATES.env.auto_reload = False


def _warm_templates() -> None:
    folder = PACKAGE_DIR / "templates"
    names = sorted(path.name for path in folder.glob("*.html"))
    for name in names:
        TEMPLATES.env.get_template(name)
    print(f"compiled {len(names)} templates", flush=True)


_warm_templates()

from detection_review.auth import add_session_middleware, require_login, review_password
from detection_review.config import ReviewConfig, load_project_env
from detection_review.exemplars import build_exemplars, image_bytes, write_detection_thumb
from detection_review.gt_eval import (
    class_metric_rows,
    coco_relpaths,
    compare_to_gt,
    comparison_metrics,
    image_file_rank,
    image_order_key,
    metric_table_rows,
    overlay_for_image,
)
from detection_review.persist import (
    SessionProgress,
    infer_session_progress,
    load_completed_results,
    load_session_progress,
    save_session_progress,
)
from detection_review.session_source import (
    MANIFEST_SOURCE,
    header_identity,
    stamp_session,
)
from detection_review.store import DatasetRun, ReviewStore, _as_bool, _resolve_image, new_run_dir
from detection_review.workload import compute_workload
from detection_review.study import DatasetSpec, StudyManifest, build_catalog


def _asset_v() -> str:
    """Cache-bust static files when they change on disk."""
    newest = 0
    static = PACKAGE_DIR / "static"
    if static.is_dir():
        for path in static.iterdir():
            try:
                newest = max(newest, int(path.stat().st_mtime))
            except OSError:
                pass
    return str(newest or 1)


def render(request: Request, name: str, context: dict | None = None, status_code: int = 200):
    ctx = dict(context or {})
    ctx.setdefault("asset_v", _asset_v())
    study_id = ctx.get("study_id")
    if study_id is None:
        study_id = request.session.get("study_id") or STATE.locked_study_id
    if study_id:
        ctx.setdefault("study_id", study_id)
    return TEMPLATES.TemplateResponse(request, name, ctx, status_code=status_code)


class AppState:
    def __init__(self) -> None:
        self.catalog: dict[str, Path] = {}
        self.locked_study_id: str | None = None
        self.manifests: dict[str, StudyManifest] = {}
        self.configs: dict[str, ReviewConfig] = {}
        self.config_path: Path | None = None
        self.data_root: Path = Path("data").resolve()
        self.output_root: Path = Path("outputs").resolve()
        self.cache_dir: Path = self.data_root / "cache"
        self.runs: dict[str, DatasetRun] = {}  # key: tester::study_id
        self.final_runs: dict[str, DatasetRun] = {}  # key: tester::study_id
        self.exemplars: dict[str, dict[str, list[dict[str, Any]]]] = {}  # key: tester::study_id
        self.dataset_index: dict[str, int] = {}  # key: tester::study_id
        self.last_results: dict[str, dict[str, Any]] = {}  # key: tester::study_id
        self.sessions: dict[str, SessionProgress] = {}  # key: tester::study_id
        self.gt_relpaths: dict[str, dict[str, str]] = {}  # key: study_id/dataset_id


STATE = AppState()

_RESERVED_LAUNCH_PATHS = frozenset(
    {
        "stage1",
        "stage2",
        "results",
        "done",
        "login",
        "logout",
        "static",
        "api",
        "health",
    }
)


def _log(message: str) -> None:
    print(message, flush=True)


def _session_key(tester: str, study_id: str) -> str:
    return f"{tester}::{study_id}"


def create_app(
    *,
    catalog: dict[str, Path] | None = None,
    locked_study_id: str | None = None,
    manifest_path: Path | None = None,
    manifest_dir: Path | None = None,
    data_root: Path | None = None,
    output_root: Path | None = None,
    password: str | None = None,
    config_path: Path | None = None,
    manifests: dict[str, StudyManifest] | None = None,
) -> FastAPI:
    load_project_env()
    if password:
        os.environ["REVIEW_PASSWORD"] = password
    if catalog is None:
        if manifests:
            catalog = {}
        else:
            catalog, derived_lock = build_catalog(manifest=manifest_path, manifest_dir=manifest_dir)
            if locked_study_id is None:
                locked_study_id = derived_lock
    if manifests:
        for sid in manifests:
            catalog.setdefault(sid, Path(f"<inputs:{sid}>"))
        if locked_study_id is None and len(manifests) == 1:
            locked_study_id = next(iter(manifests))
    STATE.catalog = catalog
    STATE.locked_study_id = locked_study_id
    STATE.manifests = dict(manifests or {})
    STATE.configs = {}
    STATE.config_path = config_path
    STATE.data_root = (data_root or Path(os.environ.get("DATA_ROOT", "data"))).resolve()
    STATE.data_root.mkdir(parents=True, exist_ok=True)
    STATE.output_root = (
        output_root or Path(os.environ.get("OUTPUT_DIR", "outputs"))
    ).resolve()
    STATE.output_root.mkdir(parents=True, exist_ok=True)
    STATE.cache_dir = STATE.data_root / "cache"
    STATE.cache_dir.mkdir(parents=True, exist_ok=True)
    STATE.runs = {}
    STATE.final_runs = {}
    STATE.exemplars = {}
    STATE.dataset_index = {}
    STATE.last_results = {}
    STATE.sessions = {}
    STATE.gt_relpaths = {}

    app = FastAPI(title="Detection Review Tool", version="0.1.0")
    add_session_middleware(app)
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")

    def _load_study(study_id: str) -> StudyManifest:
        cached = STATE.manifests.get(study_id)
        if cached is not None:
            return cached
        path = STATE.catalog.get(study_id)
        if path is None:
            raise HTTPException(400, f"Unknown study: {study_id}")
        try:
            manifest = StudyManifest.load(path)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        STATE.manifests[study_id] = manifest
        return manifest

    def _config_for(manifest: StudyManifest) -> ReviewConfig:
        cached = STATE.configs.get(manifest.study_id)
        if cached is not None:
            return cached
        cfg = ReviewConfig.load(STATE.config_path, manifest.settings)
        STATE.configs[manifest.study_id] = cfg
        return cfg

    def _study_id_for(request: Request) -> str | None:
        sid = request.session.get("study_id") or STATE.locked_study_id
        return str(sid) if sid else None

    def _page_session(request: Request) -> tuple[str, str] | None:
        tester = request.session.get("tester")
        study_id = _study_id_for(request)
        if not tester or not study_id:
            return None
        return str(tester), str(study_id)

    def _require_session(request: Request) -> tuple[str, str, StudyManifest]:
        tester = require_login(request)
        study_id = _study_id_for(request)
        if not study_id:
            raise HTTPException(400, "No study selected")
        return tester, study_id, _load_study(study_id)

    def _studies_options() -> list[dict[str, str]]:
        return [{"study_id": sid} for sid in STATE.catalog]

    def _login_context(
        request: Request,
        *,
        error: str | None = None,
        selected_study_id: str | None = None,
        tester: str | None = None,
    ) -> dict[str, Any]:
        skip_dropdown = STATE.locked_study_id is not None
        return {
            "error": error,
            "studies": _studies_options(),
            "selected_study_id": selected_study_id or STATE.locked_study_id,
            "skip_dropdown": skip_dropdown,
            "tester": tester or request.session.get("tester") or "",
            "study_id": None,
        }

    def _save_session(progress: SessionProgress) -> None:
        key = _session_key(progress.tester, progress.study_id)
        STATE.sessions[key] = progress
        STATE.dataset_index[key] = progress.dataset_index
        save_session_progress(STATE.output_root, progress)

    def _session_for(tester: str, study_id: str) -> SessionProgress:
        _hydrate_progress(tester, study_id)
        key = _session_key(tester, study_id)
        sess = STATE.sessions.get(key)
        if sess is not None:
            return sess
        sess = SessionProgress(study_id=study_id, tester=tester)
        STATE.sessions[key] = sess
        return sess

    def _hydrate_progress(tester: str, study_id: str) -> None:
        key = _session_key(tester, study_id)
        if key in STATE.sessions:
            STATE.dataset_index.setdefault(key, STATE.sessions[key].dataset_index)
            return
        manifest = _load_study(study_id)
        dataset_ids = [d.id for d in manifest.datasets]
        progress = load_session_progress(STATE.output_root, study_id, tester)
        if progress is None:
            progress = infer_session_progress(
                STATE.output_root, study_id, tester, dataset_ids
            )
        progress.dataset_index = min(progress.dataset_index, len(manifest.datasets))
        STATE.sessions[key] = progress
        STATE.dataset_index[key] = progress.dataset_index
        completed_dir = progress.resolve_last_completed(STATE.output_root)
        if completed_dir is not None and key not in STATE.last_results:
            loaded = load_completed_results(completed_dir)
            if loaded:
                STATE.last_results[key] = loaded

    def _set_resume_stage(tester: str, study_id: str, stage: str) -> None:
        sess = _session_for(tester, study_id)
        if sess.stage == stage:
            return
        sess.stage = stage
        _save_session(sess)

    def _resume_url(tester: str, study_id: str) -> str:
        _hydrate_progress(tester, study_id)
        sess = STATE.sessions.get(_session_key(tester, study_id))
        stage = sess.stage if sess else "stage1"
        if stage == "results":
            return "/results"
        if stage == "done" or _progress(tester, study_id)["complete"]:
            return "/done"
        if stage == "stage2":
            return "/stage2"
        return "/stage1"

    def _ensure_exemplars(
        key: str, spec: DatasetSpec, store: ReviewStore, manifest: StudyManifest
    ) -> None:
        if key in STATE.exemplars:
            return
        cat_names = [c["name"] for c in store.categories]
        if spec.support_coco is not None and spec.support_images_dir is not None:
            STATE.exemplars[key] = build_exemplars(
                support_coco=spec.support_coco,
                support_images_dir=spec.support_images_dir,
                category_names=cat_names,
                k=int(os.environ.get("EXEMPLAR_K", "3")),
                cache_dir=STATE.cache_dir / "exemplars" / manifest.study_id / spec.id,
            )
        else:
            STATE.exemplars[key] = {name: [] for name in cat_names}

    def _try_load_run(
        tester: str, study_id: str, spec: DatasetSpec, cfg: ReviewConfig
    ) -> DatasetRun | None:
        sess = STATE.sessions.get(_session_key(tester, study_id))
        candidates: list[Path] = []
        if sess is not None:
            current = sess.resolve_current_run(STATE.output_root)
            if current is not None:
                candidates.append(current)
        if not candidates:
            inferred = infer_session_progress(
                STATE.output_root,
                study_id,
                tester,
                [d.id for d in _load_study(study_id).datasets],
            )
            current = inferred.resolve_current_run(STATE.output_root)
            if current is not None:
                candidates.append(current)
        for run_dir in candidates:
            try:
                run = DatasetRun.load(
                    run_dir,
                    images_dir=spec.images_dir,
                    predictions_path=spec.predictions_coco,
                    top_n=cfg.stage1_top_n,
                    min_score=cfg.stage1_min_score,
                    close_open_timers=True,
                )
            except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError):
                continue
            if run.dataset_id != spec.id or run.completed:
                continue
            run.write_timing()
            return run
        return None

    def _ensure_run(tester: str, study_id: str) -> DatasetRun:
        _hydrate_progress(tester, study_id)
        manifest = _load_study(study_id)
        cfg = _config_for(manifest)
        key = _session_key(tester, study_id)
        idx = STATE.dataset_index.get(key, 0)
        if idx >= len(manifest.datasets):
            raise HTTPException(400, "Study already complete")
        spec = manifest.datasets[idx]
        existing = STATE.runs.get(key)
        if existing and existing.dataset_id == spec.id and not existing.completed:
            return existing
        loaded = _try_load_run(tester, study_id, spec, cfg)
        if loaded is not None:
            STATE.runs[key] = loaded
            _ensure_exemplars(key, spec, loaded.store, manifest)
            sess = _session_for(tester, study_id)
            sess.current_run_dir = loaded.run_dir.name
            _save_session(sess)
            return loaded
        _log(f"loading predictions {spec.id} from {spec.predictions_coco}")
        store = ReviewStore.from_predictions(
            spec.id,
            spec.images_dir,
            spec.predictions_coco,
            top_n=cfg.stage1_top_n,
            min_score=cfg.stage1_min_score,
        )
        _log(f"predictions loaded ({len(store.images)} images, {len(store.detections)} boxes)")
        run_dir = new_run_dir(STATE.output_root, manifest.study_id, tester, spec.id)
        run = DatasetRun(
            study_id=manifest.study_id,
            tester=tester,
            dataset_id=spec.id,
            run_dir=run_dir,
            store=store,
        )
        STATE.runs[key] = run
        _log("ensure_run exemplars")
        _ensure_exemplars(key, spec, store, manifest)
        _log("ensure_run write_timing")
        run.write_timing()
        _log("ensure_run save_session")
        sess = _session_for(tester, study_id)
        sess.current_run_dir = run.run_dir.name
        sess.dataset_index = idx
        if sess.stage in ("results", "done"):
            sess.stage = "stage1"
            sess.stage1_page = 1
            sess.stage2_image_id = None
        _save_session(sess)
        _log("ensure_run done")
        return run

    def _completed_run_dir_and_spec(tester: str, study_id: str) -> tuple[Path, Any]:
        sess = _session_for(tester, study_id)
        run_dir = sess.resolve_last_completed(STATE.output_root)
        if run_dir is None:
            raise HTTPException(404, "No completed model to review")
        manifest = _load_study(study_id)
        key = _session_key(tester, study_id)
        last = STATE.last_results.get(key) or {}
        dataset_id = last.get("dataset_id")
        if not dataset_id:
            try:
                timing = json.loads((run_dir / "timing.json").read_text())
            except (OSError, json.JSONDecodeError):
                timing = {}
            dataset_id = timing.get("dataset_id") if isinstance(timing, dict) else None
        spec = next((d for d in manifest.datasets if d.id == dataset_id), None)
        if spec is None:
            raise HTTPException(404, "Model for last results not found")
        return run_dir, spec

    def _enter_final_review(tester: str, study_id: str) -> None:
        _session_for(tester, study_id)
        _completed_run_dir_and_spec(tester, study_id)
        sess = _session_for(tester, study_id)
        sess.final_review = True
        _save_session(sess)

    def _leave_final_review(tester: str, study_id: str) -> None:
        sess = _session_for(tester, study_id)
        if not sess.final_review:
            return
        sess.final_review = False
        _save_session(sess)
        STATE.final_runs.pop(_session_key(tester, study_id), None)

    def _ensure_final_run(tester: str, study_id: str) -> DatasetRun:
        _hydrate_progress(tester, study_id)
        key = _session_key(tester, study_id)
        existing = STATE.final_runs.get(key)
        if existing is not None and existing.completed:
            return existing
        run_dir, spec = _completed_run_dir_and_spec(tester, study_id)
        manifest = _load_study(study_id)
        cfg = _config_for(manifest)
        try:
            run = DatasetRun.load(
                run_dir,
                images_dir=spec.images_dir,
                predictions_path=spec.predictions_coco,
                top_n=cfg.stage1_top_n,
                min_score=cfg.stage1_min_score,
                close_open_timers=True,
            )
        except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError, FileNotFoundError) as exc:
            raise HTTPException(404, "Could not load the completed review") from exc
        STATE.final_runs[key] = run
        _ensure_exemplars(f"{key}::final", spec, run.store, manifest)
        return run

    def _ensure_active_run(tester: str, study_id: str) -> DatasetRun:
        sess = _session_for(tester, study_id)
        if sess.final_review:
            return _ensure_final_run(tester, study_id)
        return _ensure_run(tester, study_id)

    def _persist_run(tester: str, study_id: str, run: DatasetRun) -> None:
        if not run.completed:
            run.write_timing()
            return
        run.write_timing()
        manifest = _load_study(study_id)
        spec = next((d for d in manifest.datasets if d.id == run.dataset_id), None)
        if spec is not None and spec.ground_truth_coco is not None:
            gt_payload = compare_to_gt(run.store.export_coco(), spec.ground_truth_coco)
            (run.run_dir / "gt_comparison_final.json").write_text(json.dumps(gt_payload, indent=2))
        loaded = load_completed_results(run.run_dir)
        if loaded:
            STATE.last_results[_session_key(tester, study_id)] = loaded

    def _progress(tester: str, study_id: str) -> dict[str, Any]:
        _hydrate_progress(tester, study_id)
        manifest = _load_study(study_id)
        key = _session_key(tester, study_id)
        idx = STATE.dataset_index.get(key, 0)
        total = len(manifest.datasets)
        done = idx >= total
        current = None if done else manifest.datasets[idx].id
        return {
            "study_id": manifest.study_id,
            "tester": tester,
            "index": idx,
            "total": total,
            "current_dataset_id": current,
            "complete": done,
        }

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        pair = _page_session(request)
        if pair:
            return RedirectResponse(_resume_url(*pair), status_code=302)
        return render(request, "login.html", _login_context(request))

    @app.post("/login")
    async def login(request: Request):
        form = await request.form()
        password = str(form.get("password") or "")
        tester = str(form.get("tester") or "").strip()
        study_id = str(form.get("study_id") or "").strip() or STATE.locked_study_id
        if password != review_password():
            return render(
                request,
                "login.html",
                _login_context(request, error="Incorrect password", selected_study_id=study_id, tester=tester),
                status_code=401,
            )
        if not tester:
            return render(
                request,
                "login.html",
                _login_context(request, error="Enter a tester name", selected_study_id=study_id, tester=tester),
                status_code=400,
            )
        if not study_id or study_id not in STATE.catalog:
            return render(
                request,
                "login.html",
                _login_context(request, error="Select a study", selected_study_id=study_id, tester=tester),
                status_code=400,
            )
        try:
            _load_study(study_id)
        except HTTPException as exc:
            return render(
                request,
                "login.html",
                _login_context(
                    request,
                    error=str(exc.detail),
                    selected_study_id=study_id,
                    tester=tester,
                ),
                status_code=400,
            )
        request.session.clear()
        stamp_session(request.session, MANIFEST_SOURCE, tester=tester, study_id=study_id)
        _hydrate_progress(tester, study_id)
        return RedirectResponse(_resume_url(tester, study_id), status_code=302)

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/", status_code=302)

    def _page_header(
        request: Request,
        tester: str,
        study_id: str,
        *,
        dataset_id: str | None = None,
        dataset_n: int | None = None,
    ):
        return header_identity(
            request.session,
            progress=_progress(tester, study_id),
            dataset_id=dataset_id,
            dataset_n=dataset_n,
        )

    def _dataset_filter_summary(tester: str, study_id: str) -> str | None:
        key = _session_key(tester, study_id)
        sess = STATE.sessions.get(key)
        if sess and sess.final_review:
            run = STATE.final_runs.get(key)
        else:
            run = STATE.runs.get(key) or STATE.final_runs.get(key)
        if run is not None:
            info = run.store.filter_info or {}
            top_n = info.get("top_n")
            min_score = info.get("min_score")
        else:
            cfg = _config_for(_load_study(study_id))
            top_n = cfg.stage1_top_n
            min_score = cfg.stage1_min_score
        parts: list[str] = []
        if top_n is not None:
            parts.append(f"Top {top_n} per image")
        if min_score is not None:
            parts.append(f"score > {min_score}")
        return " · ".join(parts) if parts else None

    def _stage_page_context(
        request: Request, tester: str, study_id: str, stage: str, *, final_review: bool = False
    ) -> dict[str, Any]:
        categories = _categories(tester, study_id)
        has_exemplars = any(c.get("exemplars") for c in categories)
        sess = _session_for(tester, study_id)
        tour_seen = sess.stage1_tour_seen if stage == "stage1" else sess.stage2_tour_seen
        return {
            "progress": _progress(tester, study_id),
            "categories": categories,
            "config": _config_for(_load_study(study_id)).to_dict(),
            "stage": stage,
            "has_exemplars": has_exemplars,
            "header": _page_header(request, tester, study_id),
            "dataset_filter": _dataset_filter_summary(tester, study_id),
            "tour_seen": tour_seen,
            "final_review": final_review,
        }

    def _stage_page(request: Request, stage: Literal["stage1", "stage2"]):
        pair = _page_session(request)
        if not pair:
            return RedirectResponse("/", status_code=302)
        tester, study_id = pair
        _log(f"GET /{stage} {tester}/{study_id}")
        prog = _progress(tester, study_id)
        final = request.query_params.get("mode") == "final"
        if final:
            try:
                _enter_final_review(tester, study_id)
                run = _ensure_final_run(tester, study_id)
            except HTTPException:
                return RedirectResponse("/done" if prog["complete"] else "/results", status_code=302)
            _set_resume_stage(tester, study_id, stage)
            return render(
                request,
                f"{stage}.html",
                _stage_page_context(request, tester, study_id, stage, final_review=True),
            )
        _leave_final_review(tester, study_id)
        if prog["complete"]:
            return RedirectResponse("/done", status_code=302)
        run = _ensure_run(tester, study_id)
        _set_resume_stage(tester, study_id, stage)
        if run.pause_other_stage(stage):
            run.write_timing()
        return render(request, f"{stage}.html", _stage_page_context(request, tester, study_id, stage))

    @app.get("/stage1", response_class=HTMLResponse)
    def stage1_page(request: Request):
        return _stage_page(request, "stage1")

    @app.get("/stage2", response_class=HTMLResponse)
    def stage2_page(request: Request):
        return _stage_page(request, "stage2")

    @app.get("/results", response_class=HTMLResponse)
    def results_page(request: Request):
        pair = _page_session(request)
        if not pair:
            return RedirectResponse("/", status_code=302)
        tester, study_id = pair
        _leave_final_review(tester, study_id)
        _set_resume_stage(tester, study_id, "results")
        key = _session_key(tester, study_id)
        manifest = _load_study(study_id)
        run = STATE.runs.get(key)
        last = STATE.last_results.get(key, {})
        categories = last.get("categories") or _categories(tester, study_id)
        gt_reviewed = last.get("gt") or (run.gt_comparison if run else None)
        gt_original = last.get("gt_original")
        dataset_id = last.get("dataset_id") or (run.dataset_id if run else None)
        spec = None
        if dataset_id:
            spec = next((d for d in manifest.datasets if d.id == dataset_id), None)
        completed_dir = _session_for(tester, study_id).resolve_last_completed(STATE.output_root)
        if completed_dir is not None:
            loaded = load_completed_results(completed_dir)
            if loaded:
                STATE.last_results[key] = loaded
                last = loaded
                if dataset_id is None:
                    dataset_id = last.get("dataset_id")
                    if dataset_id:
                        spec = next((d for d in manifest.datasets if d.id == dataset_id), None)
                categories = last.get("categories") or categories
        if last and spec is not None:
            _refresh_gt_payload(last, spec)
            gt_reviewed = last.get("gt") or gt_reviewed
            gt_original = last.get("gt_original") or gt_original
        if (
            gt_original is None
            and spec is not None
            and spec.ground_truth_coco is not None
            and spec.predictions_coco.is_file()
        ):
            gt_original = comparison_metrics(
                compare_to_gt(
                    json.loads(spec.predictions_coco.read_text()),
                    spec.ground_truth_coco,
                )
            )
            if last:
                last["gt_original"] = gt_original
        prog = _progress(tester, study_id)
        completed_n = prog["index"] if not prog["complete"] else prog["total"]
        n_images = last.get("n_images")
        if n_images is None and run is not None:
            n_images = len(run.store.images)
        if n_images is None and completed_dir is not None:
            loaded = load_completed_results(completed_dir)
            if loaded:
                n_images = loaded.get("n_images")
        timing = last.get("timing") or {
            "stage1": run.stage1.to_dict() if run else {},
            "stage2": run.stage2.to_dict() if run else {},
        }
        compare = _results_compare(request, last)
        view = _results_view(last, compare)
        gt_reviewed = view.get("gt") or gt_reviewed
        counts = view.get("counts") or last.get("counts") or (run.store.counts if run else {})
        categories = view.get("categories") or categories
        timed_view = (last.get("views") or {}).get("timed") or {}
        workload = last.get("workload")
        if not workload:
            timed_gt = timed_view.get("gt") if isinstance(timed_view, dict) else None
            workload = compute_workload(
                t1_sec=(timing.get("stage1") or {}).get("elapsed_sec"),
                t2_sec=(timing.get("stage2") or {}).get("elapsed_sec"),
                counts=(timed_view.get("counts") if isinstance(timed_view, dict) else None)
                or last.get("counts")
                or (run.store.counts if run else {}),
                n_images=n_images,
                gt_fn=timed_gt.get("fn") if isinstance(timed_gt, dict) else None,
            )
        return render(
            request,
            "results.html",
            {
                "progress": prog,
                "gt": gt_reviewed,
                "gt_original": gt_original,
                "metric_rows": metric_table_rows(gt_original, gt_reviewed),
                "class_rows": class_metric_rows(gt_original, gt_reviewed),
                "counts": counts,
                "timing": timing,
                "workload": workload,
                "n_images": n_images,
                "categories": categories,
                "stage": "results",
                "has_qaqc": bool(last.get("has_qaqc")),
                "compare": compare,
                "results_source": last.get("results_source") or "timed",
                "header": _page_header(
                    request,
                    tester,
                    study_id,
                    dataset_id=dataset_id,
                    dataset_n=completed_n or None,
                ),
                "dataset_filter": _dataset_filter_summary(tester, study_id),
            },
        )

    @app.get("/done", response_class=HTMLResponse)
    def done_page(request: Request):
        pair = _page_session(request)
        if not pair:
            return RedirectResponse("/", status_code=302)
        tester, study_id = pair
        _set_resume_stage(tester, study_id, "done")
        return render(request, "done.html", {"progress": _progress(tester, study_id)})

    def _categories(tester: str, study_id: str) -> list[dict[str, Any]]:
        key = _session_key(tester, study_id)
        sess = STATE.sessions.get(key)
        if sess and sess.final_review:
            run = STATE.final_runs.get(key)
            exemplars = STATE.exemplars.get(f"{key}::final") or {}
        else:
            run = STATE.runs.get(key)
            exemplars = STATE.exemplars.get(key) or {}
        if run is not None:
            cats = []
            for c in run.store.categories:
                name = c["name"]
                cats.append({"id": c["id"], "name": name, "exemplars": exemplars.get(name, [])})
            return sorted(cats, key=lambda c: c["name"].casefold())
        manifest = _load_study(study_id)
        coco = json.loads(manifest.datasets[0].predictions_coco.read_text())
        cats = [{"id": c["id"], "name": c["name"], "exemplars": []} for c in coco.get("categories") or []]
        return sorted(cats, key=lambda c: c["name"].casefold())

    # ---- API ----

    @app.get("/api/progress")
    def api_progress(request: Request):
        tester, study_id, _manifest = _require_session(request)
        return _progress(tester, study_id)

    @app.get("/api/categories")
    def api_categories(request: Request):
        tester, study_id, _manifest = _require_session(request)
        return _categories(tester, study_id)

    @app.get("/api/exemplars/file/{name}")
    def api_exemplar_file(name: str):
        # search cache
        for path in STATE.cache_dir.joinpath("exemplars").rglob(name):
            if path.is_file():
                return Response(path.read_bytes(), media_type="image/jpeg")
        raise HTTPException(404)

    @app.get("/api/run/status")
    def api_run_status(request: Request):
        tester, study_id, manifest = _require_session(request)
        run = _ensure_active_run(tester, study_id)
        return {
            "dataset_id": run.dataset_id,
            "stage1": run.stage1.to_dict(),
            "stage2": run.stage2.to_dict(),
            "counts": run.store.counts,
            "completed": run.completed,
            "n_detections": len(run.store.detections),
            "n_images": len(run.store.images),
            "filter": run.store.filter_info,
            "config": _config_for(manifest).to_dict(),
            "cursor": _session_for(tester, study_id).cursor(),
        }

    @app.post("/api/run/start")
    async def api_start(request: Request):
        tester, study_id, _manifest = _require_session(request)
        data = await request.json()
        stage = data.get("stage")
        if stage not in ("stage1", "stage2"):
            raise HTTPException(400, "stage must be stage1 or stage2")
        run = _ensure_run(tester, study_id)
        if run.completed:
            raise HTTPException(400, "QA/QC review is not timed")
        run.pause_other_stage(stage)
        timing = run.stage1 if stage == "stage1" else run.stage2
        timing.start()
        run.write_timing()
        return timing.to_dict()

    @app.post("/api/run/stop")
    async def api_stop(request: Request):
        tester, study_id, _manifest = _require_session(request)
        data = await request.json()
        stage = data.get("stage")
        if stage not in ("stage1", "stage2"):
            raise HTTPException(400, "stage must be stage1 or stage2")
        run = _ensure_run(tester, study_id)
        timing = run.stage1 if stage == "stage1" else run.stage2
        timing.stop()
        run.write_timing()
        return timing.to_dict()

    @app.post("/api/run/cursor")
    async def api_cursor(request: Request):
        tester, study_id, _manifest = _require_session(request)
        data = await request.json()
        sess = _session_for(tester, study_id)
        if data.get("stage1_page") is not None:
            sess.stage1_page = max(1, int(data["stage1_page"]))
        if data.get("stage1_page_size") is not None:
            size = int(data["stage1_page_size"])
            if size in (24, 48, 96):
                sess.stage1_page_size = size
        if "stage2_image_id" in data:
            val = data.get("stage2_image_id")
            sess.stage2_image_id = int(val) if val is not None else None
        if data.get("stage1_tour_seen"):
            sess.stage1_tour_seen = True
        if data.get("stage2_tour_seen"):
            sess.stage2_tour_seen = True
        _save_session(sess)
        return sess.cursor()

    @app.get("/api/patches")
    def api_patches(
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(48, ge=1, le=200),
        status: str | None = None,
        label: str | None = None,
        include_confirmed: bool = True,
        include_incorrect: bool = True,
        include_initial: bool = True,
        min_prob: float | None = Query(None, ge=0.0, le=1.0),
        max_prob: float | None = Query(None, ge=0.0, le=1.0),
        flagged_only: bool = False,
    ):
        tester, study_id, manifest = _require_session(request)
        run = _ensure_active_run(tester, study_id)
        return run.store.list_patches(
            page=page,
            page_size=page_size,
            status=status,
            label=label,
            include_confirmed=include_confirmed,
            include_incorrect=include_incorrect,
            include_initial=include_initial,
            min_prob=min_prob,
            max_prob=max_prob,
            flagged_only=flagged_only,
        )

    @app.get("/api/patches/{det_id}/thumb")
    def api_patch_thumb(det_id: int, request: Request):
        tester, study_id, manifest = _require_session(request)
        run = _ensure_active_run(tester, study_id)
        det = run.store.detections.get(det_id)
        if not det:
            raise HTTPException(404)
        thumb_size = 420
        cache = STATE.cache_dir / "thumbs" / run.dataset_id / f"{det_id}_h{thumb_size}.jpg"
        try:
            img_path = run.store.image_path(det.image_id)
            write_detection_thumb(img_path, det.bbox, cache, max_size=thumb_size)
            return Response(cache.read_bytes(), media_type="image/jpeg")
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc

    @app.get("/api/patches/{det_id}/context")
    def api_patch_context(det_id: int, request: Request):
        tester, study_id, manifest = _require_session(request)
        run = _ensure_active_run(tester, study_id)
        if det_id not in run.store.detections:
            raise HTTPException(404)
        return run.store.get_context(det_id)

    @app.patch("/api/patches/{det_id}")
    async def api_patch_bbox(det_id: int, request: Request):
        tester, study_id, _manifest = _require_session(request)
        data = await request.json()
        bbox = data.get("bbox")
        if not bbox or len(bbox) != 4:
            raise HTTPException(400, "bbox[4] required")
        run = _ensure_active_run(tester, study_id)
        run.require_stage_running("stage1")
        try:
            det = run.store.update_detection(det_id, bbox=bbox)
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc
        cache = STATE.cache_dir / "thumbs" / run.dataset_id / f"{det_id}_h420.jpg"
        cache.unlink(missing_ok=True)
        _persist_run(tester, study_id, run)
        return {"id": det.id, "bbox": det.bbox, "counts": run.store.counts}

    @app.post("/api/patches/action")
    async def api_patch_action(request: Request):
        tester, study_id, _manifest = _require_session(request)
        data = await request.json()
        action = data.get("action")
        ids = data.get("ids") or []
        label = data.get("label")
        if action not in ("relabel", "confirm", "ignore", "clear", "flag", "delete"):
            raise HTTPException(400, "action must be relabel, confirm, ignore, clear, flag, or delete")
        if not ids:
            raise HTTPException(400, "ids required")
        run = _ensure_active_run(tester, study_id)
        try:
            run.require_review_running()
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc
        try:
            if action == "relabel":
                if not label:
                    raise HTTPException(400, "label required for relabel")
                n = run.store.relabel(list(ids), label)
            elif action == "ignore":
                n = run.store.ignore(list(ids))
            elif action == "clear":
                n = run.store.clear(list(ids))
            elif action == "flag":
                n = run.store.set_flagged(list(ids), _as_bool(data.get("flagged")))
            elif action == "delete":
                n = run.store.delete_detections(list(ids))
            else:
                n = run.store.confirm(list(ids))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        _persist_run(tester, study_id, run)
        return {"updated": n, "counts": run.store.counts}

    @app.get("/api/images")
    def api_images(request: Request):
        tester, study_id, manifest = _require_session(request)
        run = _ensure_active_run(tester, study_id)
        return {"items": run.store.list_images()}

    @app.get("/api/images/{image_id}")
    def api_image_detail(image_id: int, request: Request):
        tester, study_id, manifest = _require_session(request)
        run = _ensure_active_run(tester, study_id)
        try:
            return run.store.get_image_detail(image_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/images/{image_id}/file")
    def api_image_file(image_id: int, request: Request, max_edge: int | None = 1600):
        tester, study_id, manifest = _require_session(request)
        run = _ensure_active_run(tester, study_id)
        try:
            path = run.store.image_path(image_id)
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(404, str(exc)) from exc
        return Response(image_bytes(path, max_edge=max_edge), media_type="image/jpeg")

    @app.post("/api/images/{image_id}/detections")
    async def api_add_det(image_id: int, request: Request):
        tester, study_id, _manifest = _require_session(request)
        data = await request.json()
        bbox = data.get("bbox")
        label = data.get("label")
        if not bbox or len(bbox) != 4 or not label:
            raise HTTPException(400, "bbox[4] and label required")
        run = _ensure_active_run(tester, study_id)
        run.require_stage_running("stage2")
        try:
            det = run.store.add_detection(
                image_id,
                bbox,
                label,
                flagged_for_review=_as_bool(data.get("flagged_for_review")),
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc
        _persist_run(tester, study_id, run)
        return {"id": det.id, "counts": run.store.counts}

    @app.patch("/api/images/{image_id}/detections/{det_id}")
    async def api_patch_det(image_id: int, det_id: int, request: Request):
        tester, study_id, _manifest = _require_session(request)
        data = await request.json()
        run = _ensure_active_run(tester, study_id)
        run.require_stage_running("stage2")
        try:
            det = run.store.update_detection(
                det_id, bbox=data.get("bbox"), label=data.get("label")
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc
        _persist_run(tester, study_id, run)
        return {"id": det.id, "bbox": det.bbox, "label": det.label, "counts": run.store.counts}

    @app.delete("/api/images/{image_id}/detections/{det_id}")
    def api_del_det(image_id: int, det_id: int, request: Request):
        tester, study_id, manifest = _require_session(request)
        run = _ensure_active_run(tester, study_id)
        run.require_stage_running("stage2")
        try:
            run.store.delete_detection(det_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        _persist_run(tester, study_id, run)
        return {"ok": True, "counts": run.store.counts}

    @app.post("/api/images/{image_id}/done")
    def api_image_done(image_id: int, request: Request, done: bool = True):
        tester, study_id, manifest = _require_session(request)
        run = _ensure_active_run(tester, study_id)
        run.require_stage_running("stage2")
        try:
            run.store.mark_image_done(image_id, done)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        _persist_run(tester, study_id, run)
        return {"ok": True, "fn_reviewed": done, "image_id": image_id}

    @app.post("/api/export")
    def api_export(request: Request):
        tester, study_id, manifest = _require_session(request)
        run = _ensure_run(tester, study_id)
        paths = run.export()
        return paths

    @app.post("/api/complete-dataset")
    def api_complete(request: Request):
        tester, study_id, manifest = _require_session(request)
        key = _session_key(tester, study_id)
        run = _ensure_run(tester, study_id)
        if run.stage1.running:
            run.stage1.stop()
        if run.stage2.running:
            run.stage2.stop()
        paths = run.export()
        idx = STATE.dataset_index.get(key, 0)
        spec = manifest.datasets[idx]
        gt_payload = None
        gt_original = None
        if spec.ground_truth_coco is not None:
            gt_payload = compare_to_gt(run.store.export_coco(), spec.ground_truth_coco)
            gt_original = comparison_metrics(
                compare_to_gt(
                    json.loads(spec.predictions_coco.read_text()),
                    spec.ground_truth_coco,
                )
            )
            run.gt_comparison = gt_payload
            (run.run_dir / "gt_comparison.json").write_text(json.dumps(gt_payload, indent=2))
            (run.run_dir / "gt_original.json").write_text(json.dumps(gt_original, indent=2))
            run.write_timing()
        run.freeze_reviewed_snapshot()
        run.completed = True
        run.write_timing(write_store=False)
        STATE.last_results[key] = {
            "gt": gt_payload,
            "gt_original": gt_original,
            "counts": dict(run.store.counts),
            "n_images": len(run.store.images),
            "timing": {
                "stage1": run.stage1.to_dict(),
                "stage2": run.stage2.to_dict(),
            },
            "workload": compute_workload(
                t1_sec=run.stage1.elapsed_sec(),
                t2_sec=run.stage2.elapsed_sec(),
                counts=run.store.counts,
                n_images=len(run.store.images),
                gt_fn=gt_payload.get("fn") if isinstance(gt_payload, dict) else None,
            ),
            "dataset_id": run.dataset_id,
            "has_qaqc": False,
            "results_source": "timed",
            "exported": paths,
            "review_dets": run.store.export_review_overlay(),
            "categories": [{"id": c["id"], "name": c["name"]} for c in run.store.categories],
            "views": {
                "timed": {
                    "gt": gt_payload,
                    "counts": dict(run.store.counts),
                    "review_dets": run.store.export_review_overlay(),
                    "exported": paths,
                    "categories": [{"id": c["id"], "name": c["name"]} for c in run.store.categories],
                },
                "qaqc": None,
            },
        }
        STATE.dataset_index[key] = idx + 1
        has_more = STATE.dataset_index[key] < len(manifest.datasets)
        sess = _session_for(tester, study_id)
        sess.dataset_index = idx + 1
        sess.last_completed_run_dir = run.run_dir.name
        sess.current_run_dir = None
        sess.stage = "results"
        sess.stage1_page = 1
        sess.stage2_image_id = None
        sess.final_review = False
        _save_session(sess)
        STATE.runs.pop(key, None)
        STATE.final_runs.pop(key, None)
        STATE.exemplars.pop(key, None)
        return {
            "exported": paths,
            "gt_comparison": gt_payload,
            "has_more": has_more,
            "progress": _progress(tester, study_id),
            "next_url": "/stage1" if has_more else "/done",
            "results_url": "/results",
        }

    def _gt_relpaths(study_id: str, spec) -> dict[str, str]:
        cache_key = f"{study_id}/{spec.id}"
        cached = STATE.gt_relpaths.get(cache_key)
        if cached is not None:
            return cached
        mapping: dict[str, str] = {}
        if spec.ground_truth_coco is not None and spec.ground_truth_coco.is_file():
            gt = json.loads(spec.ground_truth_coco.read_text())
            mapping = coco_relpaths(gt)
        STATE.gt_relpaths[cache_key] = mapping
        return mapping

    def _fn_image_path(study_id: str, spec, file_name: str) -> Path:
        try:
            return _resolve_image(spec.images_dir, file_name)
        except FileNotFoundError:
            pass
        original = _gt_relpaths(study_id, spec).get(Path(file_name).name)
        if original and original != file_name:
            return _resolve_image(spec.images_dir, original)
        raise FileNotFoundError(f"Image not found: {file_name} under {spec.images_dir}")

    def _results_compare(request: Request, last: dict[str, Any]) -> str:
        has_qaqc = bool(last.get("has_qaqc") or (last.get("views") or {}).get("qaqc"))
        raw = (request.query_params.get("compare") or "").strip().lower()
        if raw in {"timed", "reviewed"}:
            return "timed"
        if raw in {"qaqc", "qa/qc", "final"}:
            return "qaqc" if has_qaqc else "timed"
        return "qaqc" if has_qaqc else "timed"

    def _results_view(last: dict[str, Any], compare: str) -> dict[str, Any]:
        views = last.get("views") or {}
        view = views.get(compare)
        if isinstance(view, dict) and view:
            return view
        return {
            "gt": last.get("gt"),
            "counts": last.get("counts"),
            "review_dets": last.get("review_dets"),
            "exported": last.get("exported"),
            "categories": last.get("categories"),
        }

    def _refresh_one_view_gt(view: dict[str, Any], spec, iou_thresh: float) -> None:
        if spec is None or spec.ground_truth_coco is None:
            return
        if view.get("_gt_match_version") == "iou-first-v1" and view.get("gt"):
            return
        coco_path = Path((view.get("exported") or {}).get("coco") or "")
        if not coco_path.is_file():
            return
        view["gt"] = compare_to_gt(
            json.loads(coco_path.read_text()), spec.ground_truth_coco, iou_thresh=iou_thresh
        )
        view["_gt_match_version"] = "iou-first-v1"

    def _refresh_gt_payload(last: dict[str, Any], spec) -> dict[str, Any] | None:
        """Recompute TP/FP/FN from exported COCO so matching fixes apply without re-review."""
        if spec is None or spec.ground_truth_coco is None:
            return last.get("gt")
        views = last.get("views") or {}
        iou_thresh = float((last.get("gt") or {}).get("iou_thresh") or 0.5)
        refreshed = False
        if views:
            for key in ("timed", "qaqc"):
                view = views.get(key)
                if not isinstance(view, dict):
                    continue
                if isinstance(view.get("gt"), dict) and view["gt"].get("iou_thresh"):
                    iou_thresh = float(view["gt"].get("iou_thresh") or iou_thresh)
                before = view.get("_gt_match_version")
                _refresh_one_view_gt(view, spec, iou_thresh)
                if view.get("_gt_match_version") != before:
                    refreshed = True
            default_key = "qaqc" if last.get("has_qaqc") else "timed"
            default_view = views.get(default_key)
            if isinstance(default_view, dict) and default_view.get("gt") is not None:
                last["gt"] = default_view["gt"]
                last["_gt_match_version"] = default_view.get("_gt_match_version")
            if not refreshed and last.get("gt") and last.get("gt_original"):
                return last.get("gt")
        elif last.get("_gt_match_version") == "iou-first-v1" and last.get("gt"):
            return last.get("gt")
        else:
            try:
                last["gt"] = compare_to_gt(
                    _reviewed_coco(last), spec.ground_truth_coco, iou_thresh=iou_thresh
                )
            except HTTPException:
                return last.get("gt")
            last["_gt_match_version"] = "iou-first-v1"
            refreshed = True
        if spec.predictions_coco.is_file() and (refreshed or not last.get("gt_original")):
            last["gt_original"] = comparison_metrics(
                compare_to_gt(
                    json.loads(spec.predictions_coco.read_text()),
                    spec.ground_truth_coco,
                    iou_thresh=iou_thresh,
                )
            )
        return last.get("gt")

    def _completed_results(tester: str, study_id: str) -> tuple[dict[str, Any], Any]:
        key = _session_key(tester, study_id)
        last = STATE.last_results.get(key)
        if not last:
            raise HTTPException(404, "No completed model results")
        manifest = _load_study(study_id)
        dataset_id = last.get("dataset_id")
        spec = next((d for d in manifest.datasets if d.id == dataset_id), None)
        if spec is None:
            raise HTTPException(404, "Model for last results not found")
        _refresh_gt_payload(last, spec)
        return last, spec

    def _fn_item(gt: dict[str, Any] | None, fn_id: int) -> dict[str, Any]:
        fns = (gt or {}).get("false_negatives") or []
        for item in fns:
            if int(item["id"]) == fn_id:
                return item
        raise HTTPException(404, "Unknown false negative")

    def _review_dets(
        last: dict[str, Any], view: dict[str, Any] | None = None
    ) -> list[dict[str, Any]] | None:
        src = view if isinstance(view, dict) else last
        dets = src.get("review_dets")
        if isinstance(dets, list):
            return dets
        overlay_path = Path((src.get("exported") or {}).get("overlay") or "")
        if overlay_path.is_file():
            return json.loads(overlay_path.read_text())
        return None

    def _reviewed_coco(
        last: dict[str, Any], view: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        src = view if isinstance(view, dict) else last
        coco_path = Path((src.get("exported") or {}).get("coco") or "")
        if not coco_path.is_file():
            raise HTTPException(404, "Reviewed COCO not found")
        return json.loads(coco_path.read_text())

    @app.get("/api/results/fns")
    def api_result_fns(request: Request):
        tester, study_id, _manifest = _require_session(request)
        key = _session_key(tester, study_id)
        last = STATE.last_results.get(key) or {}
        if last:
            try:
                last, _spec = _completed_results(tester, study_id)
            except HTTPException:
                pass
        compare = _results_compare(request, last)
        view = _results_view(last, compare)
        gt = view.get("gt")
        fns = list((gt or {}).get("false_negatives") or [])
        file_rank: dict[str, int] = {}
        try:
            file_rank = image_file_rank(_reviewed_coco(last, view))
        except HTTPException:
            pass
        fns.sort(key=lambda fn: image_order_key(fn, file_rank=file_rank))
        compare_q = f"?compare={compare}"
        return {
            "total": len(fns),
            "fn": (gt or {}).get("fn", len(fns)),
            "iou_thresh": (gt or {}).get("iou_thresh"),
            "has_gt": gt is not None,
            "compare": compare,
            "items": [
                {
                    "id": int(fn["id"]),
                    "file_name": fn["file_name"],
                    "label": fn["label"],
                    "bbox": fn["bbox"],
                    "gt_ann_id": fn.get("gt_ann_id"),
                    "best_iou": fn.get("best_iou"),
                    "thumb_url": f"/api/results/fns/{int(fn['id'])}/thumb{compare_q}",
                }
                for fn in fns
            ],
        }

    @app.get("/api/results/fns/{fn_id}/thumb")
    def api_result_fn_thumb(fn_id: int, request: Request):
        tester, study_id, _manifest = _require_session(request)
        last, spec = _completed_results(tester, study_id)
        view = _results_view(last, _results_compare(request, last))
        fn = _fn_item(view.get("gt"), fn_id)
        thumb_size = 420
        cache = (
            STATE.cache_dir
            / "fn_thumbs"
            / study_id
            / tester
            / str(last.get("dataset_id") or spec.id)
            / f"{fn_id}_{fn.get('gt_ann_id', 0)}_h{thumb_size}.jpg"
        )
        try:
            img_path = _fn_image_path(study_id, spec, fn["file_name"])
            write_detection_thumb(img_path, fn["bbox"], cache, max_size=thumb_size)
            return Response(cache.read_bytes(), media_type="image/jpeg")
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc

    @app.get("/api/results/fns/{fn_id}/file")
    def api_result_fn_file(fn_id: int, request: Request, max_edge: int | None = 1600):
        tester, study_id, _manifest = _require_session(request)
        last, spec = _completed_results(tester, study_id)
        view = _results_view(last, _results_compare(request, last))
        fn = _fn_item(view.get("gt"), fn_id)
        try:
            path = _fn_image_path(study_id, spec, fn["file_name"])
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(404, str(exc)) from exc
        return Response(image_bytes(path, max_edge=max_edge), media_type="image/jpeg")

    @app.get("/api/results/fns/{fn_id}/context")
    def api_result_fn_context(fn_id: int, request: Request):
        tester, study_id, _manifest = _require_session(request)
        last, spec = _completed_results(tester, study_id)
        view = _results_view(last, _results_compare(request, last))
        fn = _fn_item(view.get("gt"), fn_id)
        if spec.ground_truth_coco is None:
            raise HTTPException(404, "No ground truth for this model")
        gt = json.loads(spec.ground_truth_coco.read_text())
        try:
            overlay = overlay_for_image(
                _reviewed_coco(last, view),
                gt,
                fn["file_name"],
                focused_gt_ann_id=int(fn["gt_ann_id"]) if fn.get("gt_ann_id") is not None else None,
                review_dets=_review_dets(last, view),
                iou_thresh=float((view.get("gt") or last.get("gt") or {}).get("iou_thresh") or 0.5),
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        overlay["image_url"] = f"/api/results/fns/{fn_id}/file"
        overlay["fn"] = {
            "id": int(fn["id"]),
            "label": fn["label"],
            "bbox": fn["bbox"],
            "gt_ann_id": fn.get("gt_ann_id"),
            "best_iou": fn.get("best_iou"),
        }
        return overlay

    @app.get("/api/health")
    def health():
        return {"ok": True, "studies": list(STATE.catalog), "locked_study_id": STATE.locked_study_id}

    return app
