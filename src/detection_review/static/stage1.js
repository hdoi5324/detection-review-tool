const state = {
  page: 1,
  pageSize: 48,
  totalPages: 1,
  selected: new Set(),
  visibleIds: [],
  anchorId: null,
  focusedId: null,
  focusedLabel: "",
  ctxBoxes: [],
  ctxImage: null,
  ctxScale: 1,
  ctxDrag: null,
  running: false,
  classSelectTouched: false,
  popupClassTouched: false,
  tick: null,
  elapsedBase: 0,
  startedAt: null,
  filter: null,
  minProb: 0.7,
  maxProb: 1,
  restoredCursor: false,
  finalReview: Boolean(window.FINAL_REVIEW),
};

const grid = document.getElementById("grid");
const pageInfo = document.getElementById("page-info");
const statusMsg = document.getElementById("status-msg");
const elapsedEl = document.getElementById("elapsed");
const workArea = document.getElementById("work-area");
const contextDialog = document.getElementById("context-dialog");

function setMsg(t) {
  statusMsg.textContent = t || "";
}

function canEdit() {
  return state.running || state.finalReview;
}

function formatSec(s) {
  return `${s.toFixed(1)}s`;
}

function updateTimerDisplay() {
  let s = state.elapsedBase;
  if (state.running && state.startedAt) {
    s += (Date.now() - state.startedAt) / 1000;
  }
  elapsedEl.textContent = formatSec(s);
}

function setInteractionEnabled(on) {
  workArea.classList.toggle("locked", !on);
  if (on) {
    if (stageTour?.isRunning()) stageTour.stop();
    showTourStartHint(false);
  }
  document.getElementById("btn-confirm").disabled = !on;
  document.getElementById("btn-ignore").disabled = !on;
  document.getElementById("btn-clear").disabled = !on;
  document.getElementById("btn-prev").disabled = !on || state.page <= 1;
  document.getElementById("btn-next").disabled = !on || state.page >= state.totalPages;
  document.getElementById("page-size").disabled = !on;
  document.getElementById("show-clear").disabled = !on;
  document.getElementById("show-confirmed").disabled = !on;
  document.getElementById("show-incorrect").disabled = !on;
  const flaggedOnly = document.getElementById("flagged-only");
  if (flaggedOnly) flaggedOnly.disabled = !on;
  document.getElementById("class-filter").disabled = !on;
  document.getElementById("relabel-select").disabled = !on;
  document.getElementById("ctx-relabel-select").disabled = !on;
  document.getElementById("ctx-confirm").disabled = !on;
  document.getElementById("ctx-ignore").disabled = !on;
  document.getElementById("ctx-clear").disabled = !on;
  const ctxFlag = document.getElementById("ctx-flag");
  if (ctxFlag) ctxFlag.disabled = !on;
  setProbFilterEnabled(on);
}

function syncSelectionClasses() {
  grid.querySelectorAll(".patch-card").forEach((card) => {
    card.classList.toggle("selected", state.selected.has(Number(card.dataset.id)));
  });
}

function selectOnly(id) {
  state.selected.clear();
  state.selected.add(id);
  state.anchorId = id;
}

function toggleSelect(id) {
  if (state.selected.has(id)) state.selected.delete(id);
  else state.selected.add(id);
  state.anchorId = id;
}

function selectRange(fromId, toId) {
  const a = state.visibleIds.indexOf(fromId);
  const b = state.visibleIds.indexOf(toId);
  state.selected.clear();
  if (a < 0 || b < 0) {
    state.selected.add(toId);
    return;
  }
  const lo = Math.min(a, b);
  const hi = Math.max(a, b);
  for (let i = lo; i <= hi; i += 1) state.selected.add(state.visibleIds[i]);
}

function selectionSummary() {
  const n = state.selected.size;
  return n ? `${n} selected` : "none selected";
}

function contextOpen() {
  return Boolean(contextDialog?.open);
}

async function refreshStatus() {
  const st = await api("/api/run/status");
  applyStageTiming(state, st.stage1);
  state.filter = st.filter;
  if (!state.restoredCursor && st.cursor) {
    state.restoredCursor = true;
    const page = Number(st.cursor.stage1_page);
    const pageSize = Number(st.cursor.stage1_page_size);
    if (page >= 1) state.page = page;
    if (pageSize === 24 || pageSize === 48 || pageSize === 96) {
      state.pageSize = pageSize;
      const sel = document.getElementById("page-size");
      if (sel) setSelectValueIfIdle(sel, pageSize);
    }
  }
  const startBtn = document.getElementById("btn-start");
  const stopBtn = document.getElementById("btn-stop");
  if (startBtn) startBtn.disabled = state.running;
  if (stopBtn) stopBtn.disabled = !state.running;
  setInteractionEnabled(canEdit());
  updateCountInfo(st.counts, st.filter);
  updateTimerDisplay();
  const resumed =
    (st.counts && (st.counts.confirmed || st.counts.incorrect)) ||
    (st.stage1 && Number(st.stage1.elapsed_closed_sec) > 0);
  if (state.finalReview) {
    setMsg("QA/QC review — not timed. Filtering, navigation, and edits are available.");
  } else if (!state.running) {
    setMsg(
      resumed
        ? "Resumed saved progress — press Start to continue"
        : "Press Start to enable Stage 1 interactions"
    );
  }
}

function cardTitle(status) {
  if (isIncorrect(status)) return "Ignored — red border, faded, not exported";
  if (isConfirmed(status)) return "Confirmed — thick class-coloured outline";
  return "Unreviewed — model prediction, dashed outline, not exported until confirmed";
}

async function loadPatches() {
  const includeClear = document.getElementById("show-clear").checked;
  const includeConfirmed = document.getElementById("show-confirmed").checked;
  const includeIncorrect = document.getElementById("show-incorrect").checked;
  const flaggedOnly = Boolean(document.getElementById("flagged-only")?.checked);
  const params = new URLSearchParams({
    page: String(state.page),
    page_size: String(state.pageSize),
    include_initial: String(includeClear),
    include_confirmed: String(includeConfirmed),
    include_incorrect: String(includeIncorrect),
    flagged_only: String(flaggedOnly),
    min_prob: String(state.minProb),
    max_prob: String(state.maxProb),
  });
  const label = document.getElementById("class-filter").value;
  if (label) params.set("label", label);
  const data = await api(`/api/patches?${params.toString()}`);
  state.page = data.page;
  state.totalPages = data.pages;
  pageInfo.textContent = `${data.items.length}/${data.total} patches, page ${data.page}/${data.pages}`;
  saveReviewCursor({ stage1_page: state.page, stage1_page_size: state.pageSize });
  updateCountInfo(data.counts, data.filter);
  document.getElementById("btn-prev").disabled = !canEdit() || state.page <= 1;
  document.getElementById("btn-next").disabled = !canEdit() || state.page >= state.totalPages;
  grid.innerHTML = "";
  state.visibleIds = data.items.map((item) => item.id);
  for (const item of data.items) {
    const card = document.createElement("div");
    card.className = `patch-card ${item.status}` + (state.selected.has(item.id) ? " selected" : "");
    card.dataset.id = String(item.id);
    card.dataset.label = item.label;
    card.style.setProperty("--class-color", classColor(item.label));
    card.style.setProperty("--thumb-aspect", String(thumbAspect(item.bbox)));
    const scoreTxt = item.score != null ? Number(item.score).toFixed(2) : "—";
    const statusTxt = STATUS_LABEL[item.status] || item.status;
    card.innerHTML = `
      <div class="thumb-wrap">
        <img loading="lazy" src="${item.thumb_url}" alt="${item.label}" />
        ${flagButtonHtml(item.flagged_for_review)}
        ${expandButtonHtml("Open full image")}
      </div>
      <div class="patch-meta">
        <div class="meta-top">
          <span class="badge ${item.status}">${statusTxt}</span>
          <span class="score">${scoreTxt}</span>
        </div>
        <div class="meta-label">${item.label}</div>
      </div>`;
    card.title = cardTitle(item.status);
    card.addEventListener("mousedown", (ev) => {
      if (ev.shiftKey) ev.preventDefault();
    });
    card.addEventListener("click", (ev) => {
      if (!canEdit()) {
        setMsg("Press Start before selecting patches");
        return;
      }
      if (ev.target.closest(".expand-btn") || ev.target.closest(".flag-btn")) return;
      ev.preventDefault();
      if (ev.shiftKey && state.anchorId != null) {
        selectRange(state.anchorId, item.id);
      } else if (ev.ctrlKey || ev.metaKey) {
        toggleSelect(item.id);
      } else {
        selectOnly(item.id);
      }
      syncSelectionClasses();
      syncDashClassSelect();
      setMsg(selectionSummary());
    });
    card.querySelector(".expand-btn").addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (!canEdit()) {
        setMsg("Press Start before opening full image");
        return;
      }
      openContext(item.id);
    });
    card.querySelector(".flag-btn").addEventListener("click", (ev) => {
      ev.stopPropagation();
      ev.preventDefault();
      toggleFlag([item.id], !item.flagged_for_review);
    });
    grid.appendChild(card);
  }
}

function ctxCanvas() {
  return document.getElementById("ctx-canvas");
}

function focusedBox() {
  return state.ctxBoxes.find((b) => b.id === state.focusedId) || null;
}

function ctxImageSize() {
  return {
    w: state.ctxImage?.naturalWidth || 1,
    h: state.ctxImage?.naturalHeight || 1,
  };
}

const CTX_BASE_ZOOM = 1.5;

const ctxZoom = initCanvasZoom({
  minusBtn: document.getElementById("ctx-zoom-out"),
  plusBtn: document.getElementById("ctx-zoom-in"),
  resetBtn: document.getElementById("ctx-zoom-reset"),
  labelEl: document.getElementById("ctx-zoom-label"),
  wrapEl: document.getElementById("ctx-zoom-wrap"),
  scrollEl: document.getElementById("ctx-zoom-wrap"),
  canvasEl: document.getElementById("ctx-canvas"),
  onChange: () => paintContext(),
});

function paintContext() {
  const canvas = ctxCanvas();
  if (!canvas || !state.ctxImage) return;
  const viewZoom = ctxZoom.get();
  const size = fitDisplaySize(
    state.ctxImage.width,
    state.ctxImage.height,
    popupDisplayOpts(CTX_BASE_ZOOM * viewZoom, { unbounded: viewZoom > 1 })
  );
  state.ctxScale = size.scale;
  canvas.width = size.width;
  canvas.height = size.height;
  const g = canvas.getContext("2d");
  drawImageBright(g, state.ctxImage, 0, 0, canvas.width, canvas.height);
  const boxes = sortBoxesImageOrder(state.ctxBoxes, { topId: state.focusedId });
  for (const b of boxes) {
    drawDetectionBox(g, b.bbox, state.ctxScale, {
      status: b.status,
      label: b.label,
      focused: b.id === state.focusedId,
      flagged: b.flagged_for_review,
    });
  }
  const focused = focusedBox();
  if (focused) drawHandles(g, focused.bbox, state.ctxScale);
}

function hoverCtxCursor(p) {
  const canvas = ctxCanvas();
  const focused = focusedBox();
  if (!canEdit() || !focused) {
    canvas.style.cursor = "default";
    return;
  }
  const handle = hitHandle(p.x, p.y, focused.bbox, state.ctxScale);
  if (handle) {
    canvas.style.cursor = CURSOR_FOR_HANDLE[handle];
    return;
  }
  if (hitBox(p.x / state.ctxScale, p.y / state.ctxScale, focused.bbox)) {
    canvas.style.cursor = "move";
    return;
  }
  canvas.style.cursor = "default";
}

function onCtxPointerDown(ev) {
  if (ev.button !== 0) return;
  if (!contextOpen() || !canEdit()) return;
  const focused = focusedBox();
  if (!focused) return;
  ev.preventDefault();
  const p = canvasEventPos(ctxCanvas(), ev);
  const handle = hitHandle(p.x, p.y, focused.bbox, state.ctxScale);
  if (handle) {
    state.ctxDrag = {
      type: "resize",
      handle,
      start: p,
      orig: focused.bbox.slice(),
    };
    return;
  }
  if (hitBox(p.x / state.ctxScale, p.y / state.ctxScale, focused.bbox)) {
    state.ctxDrag = {
      type: "move",
      start: p,
      orig: focused.bbox.slice(),
    };
  }
}

function onCtxPointerMove(ev) {
  if (!contextOpen()) return;
  const p = canvasEventPos(ctxCanvas(), ev);
  if (!state.ctxDrag) {
    hoverCtxCursor(p);
    return;
  }
  const focused = focusedBox();
  if (!focused) return;
  const { w: imgW, h: imgH } = ctxImageSize();
  const imgX = p.x / state.ctxScale;
  const imgY = p.y / state.ctxScale;
  let next;
  if (state.ctxDrag.type === "resize") {
    next = applyResize(state.ctxDrag.orig, state.ctxDrag.handle, imgX, imgY, imgW, imgH);
  } else {
    const dx = (p.x - state.ctxDrag.start.x) / state.ctxScale;
    const dy = (p.y - state.ctxDrag.start.y) / state.ctxScale;
    next = clampBbox(
      [state.ctxDrag.orig[0] + dx, state.ctxDrag.orig[1] + dy, state.ctxDrag.orig[2], state.ctxDrag.orig[3]],
      imgW,
      imgH
    );
  }
  focused.bbox = next;
  paintContext();
}

async function onCtxPointerUp() {
  if (!state.ctxDrag) return;
  const drag = state.ctxDrag;
  state.ctxDrag = null;
  const focused = focusedBox();
  if (!focused) {
    paintContext();
    return;
  }
  const unchanged = focused.bbox.every((v, i) => Math.abs(v - drag.orig[i]) < 0.5);
  if (unchanged) {
    paintContext();
    return;
  }
  try {
    await api(`/api/patches/${state.focusedId}`, {
      method: "PATCH",
      body: JSON.stringify({ bbox: focused.bbox }),
    });
    setMsg("Box updated");
    await loadPatches();
  } catch (e) {
    setMsg(e.message);
    if (state.focusedId) await openContext(state.focusedId);
  }
}

async function openContext(detId, opts = {}) {
  state.focusedId = detId;
  state.ctxDrag = null;
  const ctx = await api(`/api/patches/${detId}/context`);
  document.getElementById("ctx-title").textContent = `${ctx.file_name} — det ${detId}`;
  const ctxSelect = document.getElementById("ctx-relabel-select");
  state.focusedLabel = ctx.focused?.label || "";
  if (state.focusedLabel) setSelectValueIfIdle(ctxSelect, state.focusedLabel);
  state.popupClassTouched = false;
  state.ctxBoxes = ctx.boxes || [];
  syncFlagButton(document.getElementById("ctx-flag"), Boolean(ctx.focused?.flagged_for_review));
  if (opts.reuseImage && state.ctxImage) {
    paintContext();
  } else {
    state.ctxImage = new Image();
    state.ctxImage.onload = () => paintContext();
    state.ctxImage.src = ctx.image_url;
  }
  if (!contextDialog.open) contextDialog.showModal();
}

const btnStart = document.getElementById("btn-start");
if (btnStart) {
  btnStart.onclick = async () => {
    try {
      await api("/api/run/start", { method: "POST", body: JSON.stringify({ stage: "stage1" }) });
      await refreshStatus();
      setMsg("Stage 1 running — click a patch to select it; Shift-click for a range; Ctrl/Cmd-click to add or remove");
    } catch (e) {
      setMsg(e.message);
    }
  };
}

const btnStop = document.getElementById("btn-stop");
if (btnStop) {
  btnStop.onclick = async () => {
    try {
      await api("/api/run/stop", { method: "POST", body: JSON.stringify({ stage: "stage1" }) });
      await refreshStatus();
      setMsg("Stage 1 stopped");
    } catch (e) {
      setMsg(e.message);
    }
  };
}

document.getElementById("btn-prev").onclick = () => {
  if (!canEdit()) return;
  if (state.page > 1) {
    state.page -= 1;
    loadPatches();
  }
};
document.getElementById("btn-next").onclick = () => {
  if (!canEdit()) return;
  if (state.page < state.totalPages) {
    state.page += 1;
    loadPatches();
  }
};
document.getElementById("page-size").onchange = (e) => {
  if (!canEdit()) return;
  state.pageSize = Number(e.target.value);
  state.page = 1;
  loadPatches();
};
document.getElementById("show-clear").onchange = () => {
  if (!canEdit()) return;
  state.page = 1;
  loadPatches();
};
document.getElementById("show-confirmed").onchange = () => {
  if (!canEdit()) return;
  state.page = 1;
  loadPatches();
};
document.getElementById("show-incorrect").onchange = () => {
  if (!canEdit()) return;
  state.page = 1;
  loadPatches();
};
const flaggedOnlyEl = document.getElementById("flagged-only");
if (flaggedOnlyEl) {
  flaggedOnlyEl.onchange = () => {
    if (!canEdit()) return;
    state.page = 1;
    loadPatches();
  };
}
document.getElementById("class-filter").onchange = () => {
  if (!canEdit()) return;
  state.page = 1;
  loadPatches();
};

bindProbFilter(state, {
  canEdit,
  onChange() {
    state.page = 1;
    loadPatches();
  },
});

const ACTION_LABEL = {
  relabel: "class updated & confirmed",
  confirm: "confirmed",
  ignore: "ignored",
  clear: "undone — back to unreviewed",
  flag: "flagged for review",
  unflag: "flag cleared",
};

function currentLabels(ids) {
  return ids.map((id) => {
    if (id === state.focusedId && state.focusedLabel) return state.focusedLabel;
    const card = grid.querySelector(`.patch-card[data-id="${id}"]`);
    return card?.dataset.label || "";
  });
}

function uniqueLabels(ids) {
  return [...new Set(currentLabels(ids).filter(Boolean))];
}

function confirmNeedsRelabel(ids, label, touched) {
  const unique = uniqueLabels(ids);
  if (!label || !unique.length) return false;
  const differs = unique.some((name) => name !== label);
  return differs && (unique.length === 1 || touched);
}

function syncDashClassSelect() {
  const sel = document.getElementById("relabel-select");
  const unique = uniqueLabels([...state.selected]);
  if (unique.length === 1) setSelectValueIfIdle(sel, unique[0]);
  state.classSelectTouched = false;
}

async function applyAction(action, ids, label, fromPopup) {
  if (!canEdit()) {
    setMsg(state.finalReview ? "Unable to edit" : "Press Start first");
    return;
  }
  if (!ids.length) {
    setMsg("Select detections, or open one via expand");
    return;
  }
  const body = { action, ids };
  if (action === "relabel") body.label = label;
  try {
    const r = await api("/api/patches/action", { method: "POST", body: JSON.stringify(body) });
    setMsg(`${ACTION_LABEL[action] || action}: ${r.updated} updated`);
    if (action === "relabel" && label) showCursorNote(`Updated class to ${label}`);
    await loadPatches();
    if (contextOpen() && state.focusedId) await openContext(state.focusedId, { reuseImage: true });
    if (fromPopup && (action === "confirm" || action === "ignore" || action === "relabel")) {
      schedulePopupClose();
    }
  } catch (e) {
    setMsg(e.message);
  }
}

function actFromDashboard(action) {
  const ids = [...state.selected];
  const label = document.getElementById("relabel-select").value;
  if (action === "confirm") {
    action = confirmNeedsRelabel(ids, label, state.classSelectTouched) ? "relabel" : "confirm";
  }
  state.selected.clear();
  applyAction(action, ids, label);
}

function actFromPopup(action) {
  const ids = state.focusedId != null ? [state.focusedId] : [];
  const label = document.getElementById("ctx-relabel-select").value;
  if (action === "confirm") {
    action = confirmNeedsRelabel(ids, label, state.popupClassTouched) ? "relabel" : "confirm";
  }
  applyAction(action, ids, label, true);
}

document.getElementById("btn-confirm").onclick = () => actFromDashboard("confirm");
document.getElementById("relabel-select").addEventListener("change", () => {
  state.classSelectTouched = true;
});
document.getElementById("btn-ignore").onclick = () => actFromDashboard("ignore");
document.getElementById("btn-clear").onclick = () => actFromDashboard("clear");
document.getElementById("ctx-confirm").onclick = () => actFromPopup("confirm");
document.getElementById("ctx-relabel-select").addEventListener("change", () => {
  state.popupClassTouched = true;
});
document.getElementById("ctx-ignore").onclick = () => actFromPopup("ignore");
document.getElementById("ctx-clear").onclick = () => actFromPopup("clear");
const ctxFlagBtn = document.getElementById("ctx-flag");
if (ctxFlagBtn) {
  ctxFlagBtn.onclick = () => {
    const box = focusedBox();
    const next = !Boolean(box?.flagged_for_review);
    if (state.focusedId != null) toggleFlag([state.focusedId], next);
  };
}

contextDialog.addEventListener("close", () => {
  state.focusedId = null;
  state.focusedLabel = "";
  state.ctxBoxes = [];
  state.ctxImage = null;
  state.ctxDrag = null;
  ctxZoom.reset();
  hideCloseHint();
  cancelPopupClose();
  if (canEdit()) setPopupActionsEnabled(true);
});

const ctxCanvasEl = document.getElementById("ctx-canvas");
ctxCanvasEl.addEventListener("mousedown", onCtxPointerDown);
window.addEventListener("mousemove", onCtxPointerMove);
window.addEventListener("mouseup", onCtxPointerUp);
bindCanvasPanZoom({
  canvas: ctxCanvasEl,
  scrollEl: document.getElementById("ctx-zoom-wrap"),
  zoom: ctxZoom,
  isActive: () => contextOpen() && canEdit(),
});

const closeHint = document.getElementById("ctx-close-hint");
let closeHintTimer = null;
let popupCloseTimer = null;

function hideCloseHint() {
  clearTimeout(closeHintTimer);
  if (closeHint) closeHint.hidden = true;
}

function cancelPopupClose() {
  clearTimeout(popupCloseTimer);
  popupCloseTimer = null;
}

function setPopupActionsEnabled(on) {
  const ids = ["ctx-confirm", "ctx-ignore", "ctx-clear", "ctx-relabel-select", "ctx-flag"];
  for (const id of ids) {
    const el = document.getElementById(id);
    if (el) el.disabled = !on;
  }
}

async function toggleFlag(ids, flagged) {
  if (!canEdit()) {
    setMsg(state.finalReview ? "Unable to edit" : "Press Start first");
    return;
  }
  if (!ids.length) {
    setMsg("Select a detection first");
    return;
  }
  try {
    const r = await api("/api/patches/action", {
      method: "POST",
      body: JSON.stringify({ action: "flag", ids, flagged }),
    });
    setMsg(`${flagged ? ACTION_LABEL.flag : ACTION_LABEL.unflag}: ${r.updated} updated`);
    await loadPatches();
    if (contextOpen() && state.focusedId) await openContext(state.focusedId, { reuseImage: true });
  } catch (e) {
    setMsg(e.message);
  }
}

function schedulePopupClose() {
  cancelPopupClose();
  setPopupActionsEnabled(false);
  popupCloseTimer = setTimeout(() => {
    popupCloseTimer = null;
    if (contextDialog?.open) contextDialog.close();
  }, 1000);
}

function showCloseHint(x, y) {
  if (!closeHint) return;
  closeHint.style.left = `${x}px`;
  closeHint.style.top = `${y}px`;
  closeHint.hidden = false;
  clearTimeout(closeHintTimer);
  closeHintTimer = setTimeout(hideCloseHint, 1800);
}

contextDialog.addEventListener("click", (ev) => {
  if (ev.target !== contextDialog) return;
  showCloseHint(ev.clientX, ev.clientY);
});

let ctxResizeTimer = null;
window.addEventListener("resize", () => {
  if (!contextOpen()) return;
  clearTimeout(ctxResizeTimer);
  ctxResizeTimer = setTimeout(() => paintContext(), 120);
});

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

function tourDemoClearSelection() {
  grid.querySelectorAll(".patch-card.tour-demo").forEach((card) => {
    card.classList.remove("tour-demo", "selected");
  });
}

function tourDemoSelectOne() {
  tourDemoClearSelection();
  const card = grid.querySelector(".patch-card");
  if (card) card.classList.add("tour-demo", "selected");
}

function tourDemoSelectMulti() {
  tourDemoClearSelection();
  grid.querySelectorAll(".patch-card").forEach((card, i) => {
    if (i < 3) card.classList.add("tour-demo", "selected");
  });
}

function tourHandleDemo(step) {
  if (!step || !step.demo) return;
  if (step.demo === "selectOne") tourDemoSelectOne();
  else if (step.demo === "selectMulti") tourDemoSelectMulti();
  else if (step.demo === "clearSelection") tourDemoClearSelection();
}

function tourClearDemo(step) {
  if (
    step &&
    (step.demo === "selectOne" || step.demo === "selectMulti" || step.demo === "clearSelection")
  ) {
    tourDemoClearSelection();
  }
}

let stageTour = null;

function maybeStartStageTour(force) {
  if (state.finalReview) return;
  if (!force && state.running) return;
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
    onEnter(step) {
      tourHandleDemo(step);
    },
    onLeave(step) {
      tourClearDemo(step);
    },
    onFinish() {
      markStageTourSeen(window.REVIEW_STAGE);
      if (!state.running) showTourStartHint(true);
    },
  });
  stageTour.start();
}

registerStageTour((force) => maybeStartStageTour(force));

applyExemplarColors();
if (!state.finalReview) bindStageTimerGuards("stage1", refreshStatus, () => state.running);
onBrightnessChange(() => {
  if (contextOpen()) paintContext();
});
syncProbUi(state);
state.tick = setInterval(updateTimerDisplay, 200);
refreshStatus()
  .then(loadPatches)
  .then(() => setInteractionEnabled(canEdit()))
  .then(() => {
    if (!state.running && !state.finalReview) maybeStartStageTour(false);
  })
  .catch((e) => setMsg(e.message));
