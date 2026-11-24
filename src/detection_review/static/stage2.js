const DRAFT_ID = "draft";

const state = {
  images: [],
  index: 0,
  detail: null,
  selected: new Set(),
  selectedId: null,
  anchorId: null,
  classSelectTouched: false,
  draft: null,
  drag: null,
  scale: 1,
  running: false,
  elapsedBase: 0,
  startedAt: null,
  resumeImageId: null,
  filter: null,
  minProb: 0.7,
  maxProb: 1,
  finalReview: Boolean(window.FINAL_REVIEW),
};

const canvas = document.getElementById("img-canvas");
const ctx = canvas.getContext("2d");
const imgZoom = initCanvasZoom({
  minusBtn: document.getElementById("img-zoom-out"),
  plusBtn: document.getElementById("img-zoom-in"),
  resetBtn: document.getElementById("img-zoom-reset"),
  labelEl: document.getElementById("img-zoom-label"),
  wrapEl: document.getElementById("img-zoom-wrap"),
  scrollEl: document.getElementById("stage-scroll"),
  canvasEl: canvas,
  onChange: () => redraw(),
});
const statusMsg = document.getElementById("status-msg");
const elapsedEl = document.getElementById("elapsed");
const imgInfo = document.getElementById("img-info");
const imgReviewed = document.getElementById("img-reviewed");
const imgDoneCount = document.getElementById("img-done-count");
const workArea = document.getElementById("work-area");
const btnConfirm = document.getElementById("btn-confirm");
const btnIgnore = document.getElementById("btn-ignore");
const btnClear = document.getElementById("btn-clear");
const btnDelete = document.getElementById("btn-delete");
const btnDone = document.getElementById("btn-done-img");
const btnFlag = document.getElementById("btn-flag");
const drawLabel = document.getElementById("draw-label");
let baseImage = null;
let stageTour = null;
let tourBootstrapped = false;

function setMsg(t) {
  statusMsg.textContent = t || "";
}

function canEdit() {
  return state.running || state.finalReview;
}

function imageSize() {
  return {
    w: baseImage?.naturalWidth || state.detail?.width || 1,
    h: baseImage?.naturalHeight || state.detail?.height || 1,
  };
}

function visibleBoxes() {
  const boxes = state.detail?.boxes || [];
  const showClear = document.getElementById("show-clear").checked;
  const showConfirmed = document.getElementById("show-confirmed").checked;
  const showIncorrect = document.getElementById("show-incorrect").checked;
  const flaggedOnly = Boolean(document.getElementById("flagged-only")?.checked);
  const classFilter = document.getElementById("class-filter")?.value || "";
  return boxes.filter((b) => {
    if (isConfirmed(b.status)) {
      if (!showConfirmed) return false;
    } else if (isIncorrect(b.status)) {
      if (!showIncorrect) return false;
    } else if (!showClear) {
      return false;
    }
    if (flaggedOnly && !b.flagged_for_review) return false;
    if (classFilter && b.label !== classFilter) return false;
    if (!isConfirmed(b.status)) {
      const score = boxScore(b);
      if (score < state.minProb || score > state.maxProb) return false;
    }
    return true;
  });
}

function boxesForDraw() {
  return sortBoxesImageOrder(visibleBoxes(), { topId: state.selectedId });
}

function boxById(id) {
  if (id === DRAFT_ID) return state.draft;
  if (id == null) return null;
  return (state.detail?.boxes || []).find((b) => b.id === id) || null;
}

function selectedBox() {
  return boxById(state.selectedId);
}

function selectedIds() {
  return [...state.selected];
}

function savedSelectedIds() {
  return selectedIds().filter((id) => id !== DRAFT_ID);
}

function selectedBoxes() {
  return selectedIds().map(boxById).filter(Boolean);
}

function hasSelection() {
  return state.selected.size > 0 && selectedBoxes().length > 0;
}

function selectOnly(id) {
  state.selected.clear();
  state.selectedId = id ?? null;
  state.anchorId = id ?? null;
  if (id != null) state.selected.add(id);
}

function toggleSelect(id) {
  if (state.selected.has(id)) {
    state.selected.delete(id);
    state.selectedId = selectedIds().at(-1) ?? null;
  } else {
    state.selected.add(id);
    state.selectedId = id;
  }
  state.anchorId = id;
}

function pruneSelection() {
  const vis = new Set(visibleBoxes().map((b) => b.id));
  if (state.draft) vis.add(DRAFT_ID);
  for (const id of selectedIds()) {
    if (!vis.has(id)) state.selected.delete(id);
  }
  if (state.selectedId != null && !state.selected.has(state.selectedId)) {
    state.selectedId = selectedIds().at(-1) ?? null;
  }
  if (state.anchorId != null && !vis.has(state.anchorId)) {
    state.anchorId = state.selectedId;
  }
}

function uniqueLabels(ids) {
  return [...new Set(ids.map((id) => boxById(id)?.label).filter(Boolean))];
}

function confirmNeedsRelabel(ids, label, touched) {
  const unique = uniqueLabels(ids);
  if (!label || !unique.length) return false;
  const differs = unique.some((name) => name !== label);
  return differs && (unique.length === 1 || touched);
}

function syncDrawClassSelect() {
  const unique = uniqueLabels(savedSelectedIds());
  if (unique.length === 1) setSelectValueIfIdle(drawLabel, unique[0]);
  state.classSelectTouched = false;
}

function selectionSummary() {
  const boxes = selectedBoxes();
  const n = boxes.length;
  if (!n) return "";
  if (n === 1) {
    const hit = boxes[0];
    const hitId = boxId(hit);
    if (hitId === DRAFT_ID) return "Unsaved box — Confirm to save, adjust handles, or Delete";
    if (isInitial(hit.status)) return "Unreviewed box selected — Confirm, Ignore, or Undo";
    return "Selected — Confirm, Ignore, Undo, or Delete. Drag the centre or border to move; drag inside to draw a new box.";
  }
  return `${n} selected — Confirm, Ignore, Undo, or Delete. Ctrl/Cmd-click to add or remove.`;
}

function reviewedCount() {
  return state.images.filter((im) => im.fn_reviewed).length;
}

function hasUnlabeledDraft() {
  return Boolean(state.draft && !state.draft.label);
}

function warnAssignClass() {
  window.alert("Confirm the new box (assign a class) before leaving this image.");
}

function syncActionButtons() {
  const on = canEdit();
  const sel = hasSelection();
  const saved = savedSelectedIds();
  const boxes = selectedBoxes();
  btnDelete.disabled = !on || !sel;
  btnConfirm.disabled = !on || !sel;
  btnIgnore.disabled = !on || !saved.length;
  btnClear.disabled = !on || !saved.length;
  if (btnFlag) {
    btnFlag.disabled = !on || !sel;
    syncFlagButton(btnFlag, Boolean(boxes.length && boxes.every((b) => b.flagged_for_review)));
  }
}

function updateChrome() {
  const meta = state.images[state.index];
  if (!meta) return;
  const reviewed = Boolean(state.detail?.fn_reviewed);
  imgInfo.textContent = `${state.index + 1}/${state.images.length} images`;
  imgInfo.title = meta.file_name || "";
  imgReviewed.textContent = reviewed ? "Reviewed" : "Not reviewed";
  imgReviewed.classList.toggle("off", !reviewed);
  imgDoneCount.textContent = `${reviewedCount()} / ${state.images.length} done`;
  btnDone.textContent = reviewed ? "Unmark done" : "Image Done";
  btnDone.title = reviewed ? "Unmark image as done" : "Mark image as done";
  const on = canEdit();
  document.getElementById("btn-prev-img").disabled = !on || state.index <= 0;
  document.getElementById("btn-next-img").disabled = !on || state.index >= Math.max(0, state.images.length - 1);
  syncActionButtons();
}

function applyCounts(payload) {
  if (payload && payload.counts) updateCountInfo(payload.counts, payload.filter || state.filter);
}

function onFilterChange() {
  if (!canEdit()) return;
  pruneSelection();
  updateChrome();
  redraw();
}

function updateTimerDisplay() {
  let s = state.elapsedBase;
  if (state.running && state.startedAt) s += (Date.now() - state.startedAt) / 1000;
  elapsedEl.textContent = `${s.toFixed(1)}s`;
}

function setInteractionEnabled(on) {
  workArea.classList.toggle("locked", !on);
  if (on) {
    if (stageTour?.isRunning()) stageTour.stop();
    showTourStartHint(false);
  }
  document.getElementById("btn-prev-img").disabled = !on || state.index <= 0;
  document.getElementById("btn-next-img").disabled = !on || state.index >= Math.max(0, state.images.length - 1);
  document.getElementById("img-zoom-out").disabled = !on;
  document.getElementById("img-zoom-in").disabled = !on;
  document.getElementById("img-zoom-reset").disabled = !on;
  drawLabel.disabled = !on;
  btnDone.disabled = !on;
  document.getElementById("show-clear").disabled = !on;
  document.getElementById("show-confirmed").disabled = !on;
  document.getElementById("show-incorrect").disabled = !on;
  const flaggedOnly = document.getElementById("flagged-only");
  if (flaggedOnly) flaggedOnly.disabled = !on;
  const classFilter = document.getElementById("class-filter");
  if (classFilter) classFilter.disabled = !on;
  setProbFilterEnabled(on);
  if (!on) {
    btnDelete.disabled = true;
    btnConfirm.disabled = true;
    btnIgnore.disabled = true;
    btnClear.disabled = true;
  } else {
    syncActionButtons();
  }
}

async function refreshStatus() {
  const st = await api("/api/run/status");
  applyStageTiming(state, st.stage2);
  state.filter = st.filter;
  applyCounts(st);
  const startBtn = document.getElementById("btn-start");
  const stopBtn = document.getElementById("btn-stop");
  if (startBtn) startBtn.disabled = state.running;
  if (stopBtn) stopBtn.disabled = !state.running;
  setInteractionEnabled(canEdit());
  updateTimerDisplay();
  if (state.finalReview) {
    setMsg("QA/QC review — not timed. Filtering, navigation, and edits are available.");
  } else if (!state.running) {
    setMsg("Press Start to enable Stage 2 interactions");
  }
}

async function loadImageList() {
  const data = await api("/api/images");
  state.images = data.items;
  if (!state.images.length) {
    setMsg("No images");
    return;
  }
  let idx = 0;
  if (state.resumeImageId != null) {
    const found = state.images.findIndex((im) => im.id === state.resumeImageId);
    if (found >= 0) idx = found;
  }
  await showImage(idx);
}

async function showImage(i, opts = {}) {
  state.index = Math.max(0, Math.min(i, state.images.length - 1));
  const meta = state.images[state.index];
  state.detail = await api(`/api/images/${meta.id}`);
  state.images[state.index].fn_reviewed = Boolean(state.detail.fn_reviewed);
  state.images[state.index].n_boxes = (state.detail.boxes || []).length;
  saveReviewCursor({ stage2_image_id: meta.id });
  if (!opts.keepDraft) state.draft = null;
  if (opts.keepSelection) {
    pruneSelection();
  } else if (opts.selectedIds) {
    state.selected = new Set(opts.selectedIds);
    if (state.draft) state.selected.add(DRAFT_ID);
    state.selectedId = opts.selectedIds.at(-1) ?? (state.draft ? DRAFT_ID : null);
    state.anchorId = state.selectedId;
    pruneSelection();
  } else if (opts.selectedId != null) {
    selectOnly(opts.selectedId);
    pruneSelection();
  } else if (!opts.keepDraft) {
    selectOnly(null);
  } else {
    pruneSelection();
  }
  baseImage = new Image();
  baseImage.onload = () => {
    updateChrome();
    redraw();
    if (!tourBootstrapped && !state.running && !state.finalReview) {
      tourBootstrapped = true;
      maybeStartStageTour(false);
    }
  };
  baseImage.src = state.detail.image_url;
  if (canEdit() && !opts.keepMessage && !state.finalReview) {
    setMsg(
      state.detail.fn_reviewed
        ? "Image has been reviewed."
        : "Pinch or mouse-wheel to zoom. Two-finger drag or the scrollbars to pan. Space-drag also pans. Drag to draw a box; Ctrl/Cmd-click to add or remove a selection."
    );
  }
  updateChrome();
}

function redraw(tempBox) {
  if (!baseImage) return;
  const size = fitDisplaySize(baseImage.width, baseImage.height, stage2DisplayOpts(imgZoom.get()));
  state.scale = size.scale;
  canvas.width = size.width;
  canvas.height = size.height;
  drawImageBright(ctx, baseImage, 0, 0, canvas.width, canvas.height);
  for (const b of boxesForDraw()) {
    drawDetectionBox(ctx, b.bbox, state.scale, {
      status: b.status,
      label: b.label,
      selected: state.selected.has(b.id),
      flagged: b.flagged_for_review,
    });
  }
  if (state.draft) {
    const unlabeled = !state.draft.label;
    ctx.save();
    ctx.strokeStyle = SELECTED_COLOR;
    ctx.fillStyle = SELECTED_COLOR;
    ctx.lineWidth = 3;
    ctx.setLineDash(unlabeled ? [8, 4] : []);
    const [x, y, w, h] = state.draft.bbox;
    ctx.strokeRect(x * state.scale, y * state.scale, w * state.scale, h * state.scale);
    ctx.setLineDash([]);
    ctx.font = `${LABEL_PX}px sans-serif`;
    ctx.fillText(state.draft.label || "unlabeled — assign class", x * state.scale + 2, y * state.scale + LABEL_PX);
    ctx.restore();
  }
  const sel = selectedBox();
  if (sel && state.selected.size === 1) drawHandles(ctx, sel.bbox, state.scale);
  if (tempBox) {
    ctx.save();
    ctx.strokeStyle = SELECTED_COLOR;
    ctx.lineWidth = 3;
    ctx.setLineDash([8, 4]);
    const { x0, y0, x1, y1 } = tempBox;
    ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    ctx.restore();
  }
}

function canvasPos(ev) {
  return canvasEventPos(canvas, ev);
}

function candidateBoxes() {
  const boxes = boxesForDraw().slice();
  if (state.draft) boxes.push(state.draft);
  return boxes;
}

function boxId(box) {
  return box.id == null ? DRAFT_ID : box.id;
}

function pickBoxAt(imgX, imgY) {
  const boxes = candidateBoxes();
  const borderTol = HANDLE_HIT / Math.max(state.scale, 0.001);
  let bestBorder = null;
  let bestBorderDist = Infinity;
  for (const b of boxes) {
    const d = distanceToBoxBorder(imgX, imgY, b.bbox);
    if (d <= borderTol && d < bestBorderDist) {
      bestBorder = b;
      bestBorderDist = d;
    }
  }
  if (bestBorder) return bestBorder;
  let best = null;
  let bestArea = Infinity;
  for (const b of boxes) {
    if (!hitBox(imgX, imgY, b.bbox)) continue;
    const area = boxArea(b.bbox);
    if (area < bestArea) {
      best = b;
      bestArea = area;
    }
  }
  return best;
}

function hoverCursor(p) {
  if (!canEdit()) {
    canvas.style.cursor = "default";
    return;
  }
  const imgX = p.x / state.scale;
  const imgY = p.y / state.scale;
  const sel = selectedBox();
  if (sel && state.selected.size === 1) {
    const handle = hitHandle(p.x, p.y, sel.bbox, state.scale);
    if (handle) {
      canvas.style.cursor = CURSOR_FOR_HANDLE[handle];
      return;
    }
    if (hitMoveZone(imgX, imgY, sel.bbox, state.scale)) {
      canvas.style.cursor = "move";
      return;
    }
  }
  canvas.style.cursor = "crosshair";
}

function selectBoxAt(imgX, imgY, mods = {}) {
  const hit = pickBoxAt(imgX, imgY);
  if (!hit) {
    if (!mods.additive) {
      selectOnly(state.draft ? DRAFT_ID : null);
    }
    updateChrome();
    redraw();
    return;
  }
  const hitId = boxId(hit);
  if (mods.additive) {
    toggleSelect(hitId);
  } else {
    selectOnly(hitId);
  }
  syncDrawClassSelect();
  setMsg(selectionSummary() || "Ctrl/Cmd-click to add or remove.");
  updateChrome();
  redraw();
}

function pointerMods(ev) {
  return { additive: Boolean(ev.ctrlKey || ev.metaKey) };
}

function onPointerDown(ev) {
  if (ev.button !== 0) return;
  if (!canEdit()) {
    setMsg(state.finalReview ? "Unable to edit" : "Press Start before editing");
    return;
  }
  ev.preventDefault();
  const p = canvasPos(ev);
  const imgX = p.x / state.scale;
  const imgY = p.y / state.scale;
  const mods = pointerMods(ev);
  if (mods.additive) {
    state.drag = { type: "select", x0: p.x, y0: p.y, ...mods };
    return;
  }
  const sel = selectedBox();
  if (sel && state.selected.size === 1) {
    const handle = hitHandle(p.x, p.y, sel.bbox, state.scale);
    if (handle) {
      state.drag = {
        type: "resize",
        handle,
        start: p,
        orig: sel.bbox.slice(),
        id: state.selectedId,
      };
      return;
    }
    if (hitMoveZone(imgX, imgY, sel.bbox, state.scale)) {
      state.drag = {
        type: "move",
        start: p,
        orig: sel.bbox.slice(),
        id: state.selectedId,
      };
      canvas.style.cursor = "move";
      return;
    }
  }
  state.drag = { type: "draw", x0: p.x, y0: p.y, x1: p.x, y1: p.y };
  canvas.style.cursor = "crosshair";
}

function onPointerMove(ev) {
  const p = canvasPos(ev);
  if (!state.drag) {
    hoverCursor(p);
    return;
  }
  if (state.drag.type === "select") return;
  if (state.drag.type === "draw") {
    state.drag.x1 = p.x;
    state.drag.y1 = p.y;
    redraw(state.drag);
    return;
  }
  const { w: imgW, h: imgH } = imageSize();
  const imgX = p.x / state.scale;
  const imgY = p.y / state.scale;
  let next;
  if (state.drag.type === "resize") {
    next = applyResize(state.drag.orig, state.drag.handle, imgX, imgY, imgW, imgH);
  } else {
    const dx = (p.x - state.drag.start.x) / state.scale;
    const dy = (p.y - state.drag.start.y) / state.scale;
    next = clampBbox(
      [state.drag.orig[0] + dx, state.drag.orig[1] + dy, state.drag.orig[2], state.drag.orig[3]],
      imgW,
      imgH
    );
  }
  applyBboxLocal(state.drag.id, next);
  redraw();
}

async function onPointerUp(ev) {
  if (!state.drag) return;
  const drag = state.drag;
  state.drag = null;
  if (drag.type === "select") {
    selectBoxAt(drag.x0 / state.scale, drag.y0 / state.scale, drag);
    return;
  }
  if (drag.type === "draw") {
    const x0 = Math.min(drag.x0, drag.x1) / state.scale;
    const y0 = Math.min(drag.y0, drag.y1) / state.scale;
    const x1 = Math.max(drag.x0, drag.x1) / state.scale;
    const y1 = Math.max(drag.y0, drag.y1) / state.scale;
    const w = x1 - x0;
    const h = y1 - y0;
    if (w < MIN_BOX || h < MIN_BOX) {
      selectBoxAt(drag.x0 / state.scale, drag.y0 / state.scale, pointerMods(ev));
      return;
    }
    const { w: imgW, h: imgH } = imageSize();
    state.draft = {
      id: DRAFT_ID,
      bbox: clampBbox([x0, y0, w, h], imgW, imgH),
      label: "",
      status: DetectionState.INITIAL,
      source: "draft",
      flagged_for_review: false,
    };
    selectOnly(DRAFT_ID);
    state.classSelectTouched = false;
    setMsg("Box drawn — choose a class and press Confirm, or drag handles to adjust");
    updateChrome();
    redraw();
    return;
  }
  const box = selectedBox();
  if (!box) {
    redraw();
    return;
  }
  if (state.selectedId === DRAFT_ID) {
    redraw();
    return;
  }
  const unchanged =
    drag.orig &&
    box.bbox.every((v, i) => Math.abs(v - drag.orig[i]) < 0.5);
  if (unchanged) {
    redraw();
    return;
  }
  try {
    await api(`/api/images/${state.detail.id}/detections/${state.selectedId}`, {
      method: "PATCH",
      body: JSON.stringify({ bbox: box.bbox }),
    });
    setMsg("Box updated");
  } catch (e) {
    setMsg(e.message);
    await showImage(state.index, { selectedId: state.selectedId, keepMessage: true });
  }
}

function applyBboxLocal(id, bbox) {
  if (id === DRAFT_ID && state.draft) {
    state.draft.bbox = bbox;
    return;
  }
  const box = (state.detail?.boxes || []).find((b) => b.id === id);
  if (box) box.bbox = bbox;
}

const ACTION_LABEL = {
  relabel: "class updated & confirmed",
  confirm: "confirmed",
  ignore: "ignored",
  clear: "undone — back to unreviewed",
};

async function saveDraft(label) {
  const r = await api(`/api/images/${state.detail.id}/detections`, {
    method: "POST",
    body: JSON.stringify({
      bbox: state.draft.bbox,
      label,
      flagged_for_review: Boolean(state.draft.flagged_for_review),
    }),
  });
  state.draft = null;
  setMsg(`Saved box (${label})`);
  applyCounts(r);
  await showImage(state.index, { selectedId: r.id, keepMessage: true });
  return r.id;
}

async function applyBoxAction(action) {
  if (!canEdit() || !hasSelection()) {
    setMsg(canEdit() ? "Click a box first" : "Press Start first");
    return;
  }
  const label = drawLabel.value;
  const ids = savedSelectedIds();
  const draftSelected = state.selected.has(DRAFT_ID) && state.draft;
  let createdId = null;
  if (draftSelected && (action === "confirm" || action === "relabel")) {
    if (!label) {
      setMsg("Choose a class first");
      return;
    }
    try {
      createdId = await saveDraft(label);
    } catch (e) {
      setMsg(e.message);
      return;
    }
    if (!ids.length) return;
  }
  if (!ids.length) {
    if (action === "ignore" || action === "clear") return;
    return;
  }
  if (action === "confirm" && confirmNeedsRelabel(ids, label, state.classSelectTouched)) action = "relabel";
  if (action === "relabel" && !label) {
    setMsg("Choose a class first");
    return;
  }
  const body = { action, ids };
  if (action === "relabel") body.label = label;
  try {
    const r = await api("/api/patches/action", { method: "POST", body: JSON.stringify(body) });
    applyCounts(r);
    const n = r.updated ?? ids.length;
    setMsg(n === 1 ? ACTION_LABEL[action] || action : `${ACTION_LABEL[action] || action}: ${n} updated`);
    if (action === "relabel" && label) showCursorNote(`Updated class to ${label}`);
    const keep = createdId != null ? ids.concat(createdId) : ids;
    await showImage(state.index, {
      selectedIds: keep,
      keepMessage: true,
      keepDraft: Boolean(state.draft),
    });
  } catch (e) {
    setMsg(e.message);
  }
}

async function deleteSelected() {
  if (!canEdit() || !hasSelection()) return;
  let discardedDraft = false;
  if (state.selected.has(DRAFT_ID) && state.draft) {
    state.draft = null;
    state.selected.delete(DRAFT_ID);
    discardedDraft = true;
  }
  const ids = savedSelectedIds();
  if (!ids.length) {
    selectOnly(null);
    setMsg("Unsaved box discarded — draw again if needed");
    updateChrome();
    redraw();
    return;
  }
  try {
    const r = await api("/api/patches/action", {
      method: "POST",
      body: JSON.stringify({ action: "delete", ids }),
    });
    applyCounts(r);
    const n = r.updated ?? ids.length;
    setMsg(n === 1 && !discardedDraft ? "Deleted" : `Deleted ${n}${discardedDraft ? " plus draft" : ""}`);
    await showImage(state.index, { keepMessage: true, keepDraft: Boolean(state.draft) });
  } catch (e) {
    setMsg(e.message);
  }
}

function goToImage(i) {
  if (!canEdit()) return;
  if (hasUnlabeledDraft()) {
    warnAssignClass();
    return;
  }
  showImage(i);
}

document.getElementById("show-clear").onchange = onFilterChange;
document.getElementById("show-confirmed").onchange = onFilterChange;
document.getElementById("show-incorrect").onchange = onFilterChange;
const flaggedOnlyEl = document.getElementById("flagged-only");
if (flaggedOnlyEl) flaggedOnlyEl.onchange = onFilterChange;
const classFilterEl = document.getElementById("class-filter");
if (classFilterEl) classFilterEl.onchange = onFilterChange;
bindProbFilter(state, { canEdit, onChange: onFilterChange });

btnConfirm.onclick = () => applyBoxAction("confirm");
btnIgnore.onclick = () => applyBoxAction("ignore");
btnClear.onclick = () => applyBoxAction("clear");
btnDelete.onclick = () => deleteSelected();
drawLabel.addEventListener("change", () => {
  state.classSelectTouched = true;
});
if (btnFlag) {
  btnFlag.onclick = async () => {
    if (!canEdit() || !hasSelection()) return;
    const boxes = selectedBoxes();
    const next = !boxes.every((b) => b.flagged_for_review);
    const ids = savedSelectedIds();
    if (state.selected.has(DRAFT_ID) && state.draft) {
      state.draft.flagged_for_review = next;
      if (!ids.length) {
        syncActionButtons();
        redraw();
        setMsg(next ? "Draft flagged — will save with Confirm" : "Draft flag cleared");
        return;
      }
    }
    if (!ids.length) return;
    try {
      const r = await api("/api/patches/action", {
        method: "POST",
        body: JSON.stringify({ action: "flag", ids, flagged: next }),
      });
      applyCounts(r);
      setMsg(next ? (ids.length === 1 ? "Flagged for review" : `Flagged ${ids.length} for review`) : ids.length === 1 ? "Flag cleared" : `Cleared flag on ${ids.length}`);
      await showImage(state.index, {
        selectedIds: ids,
        keepMessage: true,
        keepDraft: Boolean(state.draft),
      });
    } catch (e) {
      setMsg(e.message);
    }
  };
}

btnDone.onclick = async () => {
  if (!canEdit() || !state.detail) return;
  const next = !state.detail.fn_reviewed;
  try {
    await api(`/api/images/${state.detail.id}/done?done=${next}`, { method: "POST" });
    state.detail.fn_reviewed = next;
    state.images[state.index].fn_reviewed = next;
    updateChrome();
    setMsg(next ? "Image has been reviewed." : "Unmarked — this image is not reviewed");
  } catch (e) {
    setMsg(e.message);
  }
};

document.getElementById("btn-prev-img").onclick = () => goToImage(state.index - 1);
document.getElementById("btn-next-img").onclick = () => goToImage(state.index + 1);

const btnStart = document.getElementById("btn-start");
if (btnStart) {
  btnStart.onclick = async () => {
    try {
      await api("/api/run/start", { method: "POST", body: JSON.stringify({ stage: "stage2" }) });
      await refreshStatus();
      setMsg("Stage 2 running — pinch to zoom, two-finger drag or scrollbars to pan, drag to draw a box.");
    } catch (e) {
      setMsg(e.message);
    }
  };
}
const btnStop = document.getElementById("btn-stop");
if (btnStop) {
  btnStop.onclick = async () => {
    try {
      await api("/api/run/stop", { method: "POST", body: JSON.stringify({ stage: "stage2" }) });
      await refreshStatus();
      setMsg("Stage 2 stopped");
    } catch (e) {
      setMsg(e.message);
    }
  };
}

const btnComplete = document.getElementById("btn-complete");
if (btnComplete) btnComplete.onclick = async () => {
  if (hasUnlabeledDraft()) {
    warnAssignClass();
    return;
  }
  if (!confirm("Export reviewed COCO and complete this model?")) return;
  try {
    if (state.running) {
      await api("/api/run/stop", { method: "POST", body: JSON.stringify({ stage: "stage2" }) });
    }
    const r = await api("/api/complete-dataset", { method: "POST", body: "{}" });
    window.location.href = r.results_url || "/results";
  } catch (e) {
    setMsg(e.message);
  }
};

canvas.addEventListener("mousedown", onPointerDown);
window.addEventListener("mousemove", onPointerMove);
window.addEventListener("mouseup", onPointerUp);
bindCanvasPanZoom({
  canvas,
  scrollEl: document.getElementById("stage-scroll"),
  zoom: imgZoom,
  isActive: () => canEdit(),
});

window.addEventListener("keydown", (ev) => {
  if (!canEdit()) return;
  const tag = (ev.target && ev.target.tagName) || "";
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
  if (ev.key === "Escape") {
    if (state.selected.size === 1 && state.selected.has(DRAFT_ID)) {
      deleteSelected();
      return;
    }
    selectOnly(null);
    updateChrome();
    redraw();
    return;
  }
  if (ev.key === "Delete" || ev.key === "Backspace") {
    ev.preventDefault();
    deleteSelected();
  }
  if (ev.key === "Enter") {
    ev.preventDefault();
    applyBoxAction("confirm");
  }
});

let resizeTimer = null;
function scheduleStage2Redraw() {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => redraw(), 80);
}
window.addEventListener("resize", scheduleStage2Redraw);
const stageScroll = document.getElementById("stage-scroll");
if (stageScroll && typeof ResizeObserver === "function") {
  const stageResize = new ResizeObserver(scheduleStage2Redraw);
  stageResize.observe(stageScroll);
}

function tourStepsAvailable() {
  return (window.STAGE_TOUR || []).filter((step) => {
    if (!step) return false;
    const selectors = step.targets && step.targets.length ? step.targets : step.target ? [step.target] : [];
    if (!selectors.length) return false;
    try {
      return selectors.some((sel) => document.querySelector(sel));
    } catch (_) {
      return false;
    }
  });
}

function maybeStartStageTour(force) {
  if (state.finalReview) return;
  if (!force && state.running) return;
  if (!baseImage && !force) return;
  if (!force && isStageTourSeen()) {
    showTourStartHint(true);
    return;
  }
  const steps = tourStepsAvailable();
  if (!steps.length) {
    showTourStartHint(true);
    return;
  }
  if (force && stageTour?.isRunning()) stageTour.stop();
  if (!force && stageTour?.isRunning()) return;
  showTourStartHint(false);
  stageTour = createTour(steps, {
    onFinish() {
      markStageTourSeen(window.REVIEW_STAGE);
      if (!state.running) showTourStartHint(true);
    },
  });
  stageTour.start();
}

registerStageTour((force) => maybeStartStageTour(force));

applyExemplarColors();
if (!state.finalReview) bindStageTimerGuards("stage2", refreshStatus, () => state.running);
onBrightnessChange(() => redraw());
syncProbUi(state);
setInterval(updateTimerDisplay, 200);
refreshStatus()
  .then(loadImageList)
  .then(() => setInteractionEnabled(canEdit()))
  .catch((e) => setMsg(e.message));
