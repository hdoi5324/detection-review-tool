const CLASS_PALETTE = [
  "#2471a3",
  "#1e8449",
  "#7d3c98",
  "#d35400",
  "#117a65",
  "#1a5276",
  "#b7950b",
  "#6c3483",
  "#148f77",
  "#2e86ab",
  "#af7ac5",
  "#16a085",
];

const SELECTED_COLOR = "#c6ff00";
const INCORRECT_COLOR = "#ff1744";
const GT_COLOR = "#f9a825";
const LABEL_PX = 18;

const DetectionState = Object.freeze({
  INITIAL: "initial",
  CONFIRMED: "confirmed",
  INCORRECT: "incorrect",
});

const STATUS_LABEL = {
  initial: "unreviewed",
  confirmed: "confirmed",
  incorrect: "ignored",
};

function classColor(name) {
  const cats = window.CATEGORIES || [];
  const idx = cats.findIndex((c) => c.name === name);
  const i = idx >= 0 ? idx : Math.abs(String(name).split("").reduce((a, ch) => a + ch.charCodeAt(0), 0));
  return CLASS_PALETTE[i % CLASS_PALETTE.length];
}

function applyExemplarColors() {
  document.querySelectorAll(".ex-block").forEach((block) => {
    const name = block.querySelector(".ex-name")?.textContent?.trim();
    if (name) block.style.setProperty("--class-color", classColor(name));
  });
}

function isConfirmed(status) {
  return status === DetectionState.CONFIRMED;
}

function isIncorrect(status) {
  return status === DetectionState.INCORRECT;
}

function isInitial(status) {
  return !isConfirmed(status) && !isIncorrect(status);
}

function detectionBorderColor(status, label) {
  return isIncorrect(status) ? INCORRECT_COLOR : classColor(label);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    credentials: "same-origin",
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || JSON.stringify(j);
    } catch (_) {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function thumbAspect(bbox) {
  const w = Number(bbox?.[2]);
  const h = Number(bbox?.[3]);
  if (!(w > 0) || !(h > 0)) return 1;
  return w / h;
}

function expandButtonHtml(title) {
  const t = title || "Open full image";
  return `<button type="button" class="expand-btn" title="${t}" aria-label="${t}">
            <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
              <path fill="currentColor" d="M3 3h7v2H5v5H3V3zm11 0h7v7h-2V5h-5V3zM3 14h2v5h5v2H3v-7zm16 0h2v7h-7v-2h5v-5z"/>
            </svg>
          </button>`;
}

/** Font Awesome 4 `fa-flag` / `fa-flag-o` (from fontawesome-webfont.svg, flipped to SVG y-down). */
const FLAG_VIEWBOX = "0 0 1792 1792";
const FLAG_PATH_FILLED =
  "M320 1280q0 -72 -64 -110v-1266q0 -13 -9.5 -22.5t-22.5 -9.5h-64q-13 0 -22.5 9.5t-9.5 22.5v1266q-64 38 -64 110q0 53 37.5 90.5t90.5 37.5t90.5 -37.5t37.5 -90.5zM1792 1216v-763q0 -25 -12.5 -38.5t-39.5 -27.5q-215 -116 -369 -116q-61 0 -123.5 22t-108.5 48t-115.5 48t-142.5 22q-192 0 -464 -146q-17 -9 -33 -9q-26 0 -45 19t-19 45v742q0 32 31 55q21 14 79 43q236 120 421 120q107 0 200 -29t219 -88q38 -19 88 -19q54 0 117.5 21t110 47t88 47t54.5 21q26 0 45 -19t19 -45z";
const FLAG_PATH_HOLLOW =
  "M1664 491v616q-169 -91 -306 -91q-82 0 -145 32q-100 49 -184 76.5t-178 27.5q-173 0 -403 -127v-599q245 113 433 113q55 0 103.5 -7.5t98 -26t77 -31t82.5 -39.5l28 -14q44 -22 101 -22q120 0 293 92zM320 1280q0 -35 -17.5 -64t-46.5 -46v-1266q0 -14 -9 -23t-23 -9h-64q-14 0 -23 9t-9 23v1266q-29 17 -46.5 46t-17.5 64q0 53 37.5 90.5t90.5 37.5t90.5 -37.5t37.5 -90.5zM1792 1216v-763q0 -39 -35 -57q-10 -5 -17 -9q-218 -116 -369 -116q-88 0 -158 35l-28 14q-64 33 -99 48t-91 29t-114 14q-102 0 -235.5 -44t-228.5 -102q-15 -9 -33 -9q-16 0 -32 8q-32 19 -32 56v742q0 35 31 55q35 21 78.5 42.5t114 52t152.5 49.5t155 19q112 0 209 -31t209 -86q38 -19 89 -19q122 0 310 112q22 12 31 17q31 16 62 -2q31 -20 31 -55z";

function flagSvgInner(flagged) {
  const d = flagged ? FLAG_PATH_FILLED : FLAG_PATH_HOLLOW;
  return `<g transform="translate(0 1536) scale(1 -1)"><path fill="currentColor" d="${d}"/></g>`;
}

function flagButtonHtml(flagged, opts) {
  const on = Boolean(flagged);
  const extra = (opts && opts.className) || "";
  const title = on ? "Flagged for review — click to clear" : "Flag for review";
  return `<button type="button" class="flag-btn${on ? " flagged" : ""}${extra ? ` ${extra}` : ""}" title="${title}" aria-label="${title}" aria-pressed="${on}">
            <svg viewBox="${FLAG_VIEWBOX}" width="14" height="14" aria-hidden="true">${flagSvgInner(on)}</svg>
          </button>`;
}

function syncFlagButton(btn, flagged) {
  if (!btn) return;
  const on = Boolean(flagged);
  btn.classList.toggle("flagged", on);
  btn.setAttribute("aria-pressed", String(on));
  const title = on ? "Flagged for review — click to clear" : "Flag for review";
  btn.title = title;
  btn.setAttribute("aria-label", title);
  const svg = btn.querySelector("svg");
  if (svg) {
    svg.setAttribute("viewBox", FLAG_VIEWBOX);
    svg.innerHTML = flagSvgInner(on);
  }
}

const BRIGHTNESS_KEY = "detection_review_brightness";
const BRIGHTNESS_MIN = 50;
const BRIGHTNESS_MAX = 400;
const BRIGHTNESS_DEFAULT = 100;
const brightnessListeners = [];

function clampBrightnessPct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return BRIGHTNESS_DEFAULT;
  return Math.min(BRIGHTNESS_MAX, Math.max(BRIGHTNESS_MIN, Math.round(n / 10) * 10));
}

function brightnessFactor() {
  const raw = Number.parseFloat(
    document.documentElement.style.getPropertyValue("--image-brightness")
  );
  return Number.isFinite(raw) && raw > 0 ? raw : 1;
}

function applyBrightnessPct(pct, fire) {
  const next = clampBrightnessPct(pct);
  document.documentElement.style.setProperty("--image-brightness", String(next / 100));
  const slider = document.getElementById("brightness-slider");
  const label = document.getElementById("brightness-label");
  const reset = document.getElementById("brightness-reset");
  if (slider && slider.value !== String(next)) slider.value = String(next);
  if (label) label.textContent = `${next}%`;
  if (reset) reset.disabled = next === BRIGHTNESS_DEFAULT;
  try {
    localStorage.setItem(BRIGHTNESS_KEY, String(next));
  } catch (_) {}
  if (fire !== false) brightnessListeners.forEach((fn) => fn(next));
}

function drawImageBright(ctx, img, dx, dy, dw, dh) {
  const factor = brightnessFactor();
  ctx.save();
  if (Math.abs(factor - 1) > 1e-6) ctx.filter = `brightness(${factor})`;
  ctx.drawImage(img, dx, dy, dw, dh);
  ctx.restore();
}

function onBrightnessChange(fn) {
  if (typeof fn === "function") brightnessListeners.push(fn);
}

function initBrightnessControl() {
  const slider = document.getElementById("brightness-slider");
  if (!slider) return;
  let stored = BRIGHTNESS_DEFAULT;
  try {
    stored = clampBrightnessPct(localStorage.getItem(BRIGHTNESS_KEY) || BRIGHTNESS_DEFAULT);
  } catch (_) {}
  applyBrightnessPct(stored, false);
  slider.addEventListener("input", () => applyBrightnessPct(slider.value));
  const reset = document.getElementById("brightness-reset");
  if (reset) reset.addEventListener("click", () => applyBrightnessPct(BRIGHTNESS_DEFAULT));
}

function paintFocusHighlight(ctx, rx, ry, rw, rh) {
  ctx.globalAlpha = 0.18;
  ctx.fillStyle = SELECTED_COLOR;
  ctx.fillRect(rx, ry, rw, rh);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 2;
  ctx.strokeRect(rx - 7, ry - 7, rw + 14, rh + 14);
  ctx.strokeStyle = SELECTED_COLOR;
  ctx.lineWidth = 5;
  ctx.strokeRect(rx - 3, ry - 3, rw + 6, rh + 6);
}

/** Typical Stage 1 / FN popup display: height ~720px, width follows aspect. */
const DISPLAY_TARGET_HEIGHT = 720;
const DISPLAY_POPUP_MAX_WIDTH = 1000;

function fitDisplaySize(imgW, imgH, opts) {
  const o = opts || {};
  const targetHeight = o.targetHeight || DISPLAY_TARGET_HEIGHT;
  const maxWidth = o.maxWidth == null ? Infinity : o.maxWidth;
  const maxHeight = o.maxHeight == null ? Infinity : o.maxHeight;
  if (!(imgW > 0) || !(imgH > 0)) {
    const side = Math.min(targetHeight, maxWidth, maxHeight);
    return { width: side, height: side, scale: 1 };
  }
  const aspect = imgW / imgH;
  let height = Math.min(targetHeight, maxHeight);
  let width = height * aspect;
  if (width > maxWidth) {
    width = maxWidth;
    height = width / aspect;
  }
  if (height > maxHeight) {
    height = maxHeight;
    width = height * aspect;
  }
  width = Math.max(1, Math.round(width));
  height = Math.max(1, Math.round(height));
  return { width, height, scale: width / imgW };
}

function popupDisplayOpts(scale, extra) {
  const s = scale && scale > 0 ? scale : 1;
  const targetHeight = Math.round(DISPLAY_TARGET_HEIGHT * s);
  const maxWidth = Math.round(DISPLAY_POPUP_MAX_WIDTH * s);
  if (extra && extra.unbounded) {
    return { targetHeight, maxWidth };
  }
  const vhFrac = s > 1 ? 0.88 : 0.72;
  return {
    targetHeight,
    maxWidth: Math.min(maxWidth, Math.floor(window.innerWidth * 0.94)),
    maxHeight: Math.min(targetHeight, Math.floor(window.innerHeight * vhFrac)),
  };
}

function bboxXY(box) {
  const bbox = box && box.bbox ? box.bbox : [0, 0];
  return [Number(bbox[0]) || 0, Number(bbox[1]) || 0];
}

function sortBoxesImageOrder(boxes, opts) {
  const topId = opts && opts.topId;
  return boxes.slice().sort((a, b) => {
    const [ax, ay] = bboxXY(a);
    const [bx, by] = bboxXY(b);
    if (ay !== by) return ay - by;
    if (ax !== bx) return ax - bx;
    const aTop = Boolean(a.focused) || (topId != null && a.id === topId);
    const bTop = Boolean(b.focused) || (topId != null && b.id === topId);
    if (aTop !== bTop) return aTop ? 1 : -1;
    return (Number(a.id) || 0) - (Number(b.id) || 0);
  });
}

const VIEW_ZOOM_MIN = 0.5;
const VIEW_ZOOM_MAX = 3;
const VIEW_ZOOM_STEP = 0.25;

function clampViewZoom(z) {
  return Math.min(VIEW_ZOOM_MAX, Math.max(VIEW_ZOOM_MIN, z));
}

function formatViewZoom(z) {
  return `${Math.round(z * 100)}%`;
}

function roundViewZoomStep(z) {
  return Math.round(z / VIEW_ZOOM_STEP) * VIEW_ZOOM_STEP;
}

/** Wire − / + / Reset controls; calls onChange(viewZoom) after each change. */
function initCanvasZoom(opts) {
  const o = opts || {};
  const minusBtn = o.minusBtn;
  const plusBtn = o.plusBtn;
  const resetBtn = o.resetBtn;
  const labelEl = o.labelEl;
  const wrapEl = o.wrapEl;
  const scrollEl = o.scrollEl;
  const canvasEl = o.canvasEl;
  let viewZoom = clampViewZoom(o.initial == null ? 1 : o.initial);

  function syncUi() {
    if (minusBtn) minusBtn.disabled = viewZoom <= VIEW_ZOOM_MIN + 1e-9;
    if (plusBtn) plusBtn.disabled = viewZoom >= VIEW_ZOOM_MAX - 1e-9;
    if (resetBtn) resetBtn.disabled = Math.abs(viewZoom - 1) < 1e-9;
    if (labelEl) labelEl.textContent = formatViewZoom(viewZoom);
    if (wrapEl) wrapEl.classList.toggle("zoomed", viewZoom > 1);
    if (scrollEl) scrollEl.classList.toggle("zoomed", viewZoom > 1);
  }

  function setZoom(z, fire, snap) {
    const next = snap === false ? clampViewZoom(z) : clampViewZoom(roundViewZoomStep(z));
    if (Math.abs(next - viewZoom) < 1e-9) {
      syncUi();
      return false;
    }
    viewZoom = next;
    syncUi();
    if (fire !== false && o.onChange) o.onChange(viewZoom);
    return true;
  }

  function viewportCenter() {
    const el = scrollEl || wrapEl;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
  }

  function zoomToward(z, clientX, clientY, snap) {
    const canvas = canvasEl || (wrapEl && wrapEl.querySelector("canvas"));
    const scroller = scrollEl || wrapEl;
    if (!canvas || !scroller || clientX == null || clientY == null) {
      setZoom(z, true, snap);
      return;
    }
    const oldRect = canvas.getBoundingClientRect();
    const fracX = oldRect.width ? (clientX - oldRect.left) / oldRect.width : 0.5;
    const fracY = oldRect.height ? (clientY - oldRect.top) / oldRect.height : 0.5;
    if (!setZoom(z, true, snap)) return;
    const newRect = canvas.getBoundingClientRect();
    scroller.scrollLeft += newRect.left + fracX * newRect.width - clientX;
    scroller.scrollTop += newRect.top + fracY * newRect.height - clientY;
  }

  if (minusBtn) {
    minusBtn.addEventListener("click", () => {
      const mid = viewportCenter();
      if (mid) zoomToward(viewZoom - VIEW_ZOOM_STEP, mid.clientX, mid.clientY, true);
      else setZoom(viewZoom - VIEW_ZOOM_STEP);
    });
  }
  if (plusBtn) {
    plusBtn.addEventListener("click", () => {
      const mid = viewportCenter();
      if (mid) zoomToward(viewZoom + VIEW_ZOOM_STEP, mid.clientX, mid.clientY, true);
      else setZoom(viewZoom + VIEW_ZOOM_STEP);
    });
  }
  if (resetBtn) {
    resetBtn.addEventListener("click", () => setZoom(1));
  }

  syncUi();

  return {
    get() {
      return viewZoom;
    },
    set(z) {
      setZoom(z);
    },
    apply(z, opts) {
      const spec = opts || {};
      setZoom(z, spec.fire, spec.snap);
    },
    zoomToward,
    reset() {
      setZoom(1, false);
    },
  };
}

function typingInField(ev) {
  const el = ev.target;
  if (!el) return false;
  const tag = el.tagName || "";
  return tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || Boolean(el.isContentEditable);
}

function wheelZoomFactor(ev) {
  let dy = ev.deltaY;
  if (dy === 0) dy = ev.deltaX;
  if (ev.deltaMode === 1) dy *= 16;
  if (ev.deltaMode === 2) dy *= 800;
  return Math.min(1.15, Math.max(0.87, Math.exp(-dy * 0.0018)));
}

function wheelIsPinchZoom(ev) {
  return Boolean(ev.ctrlKey || ev.metaKey);
}

function wheelLooksLikeMouseWheel(ev) {
  if (ev.deltaMode === 1 || ev.deltaMode === 2) return true;
  if (Math.abs(ev.deltaX) > 1 && Math.abs(ev.deltaY) > 1) return false;
  return Math.abs(ev.deltaY) >= 40 && Math.abs(ev.deltaX) < 1;
}

function scrollerCanPan(el) {
  return el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
}

/** Pinch / mouse-wheel zoom toward the pointer. Two-finger trackpad drag pans. Space-drag or middle-mouse drag also pan. */
function bindCanvasPanZoom(opts) {
  const o = opts || {};
  const canvas = o.canvas;
  const scrollEl = o.scrollEl;
  const zoom = o.zoom;
  if (!canvas || !scrollEl || !zoom) return { isPanning() { return false; } };

  let spaceDown = false;
  let pan = null;

  function isActive() {
    return !o.isActive || o.isActive();
  }

  function syncPanClass() {
    canvas.classList.toggle("pan-ready", spaceDown && !pan);
    canvas.classList.toggle("panning", Boolean(pan));
  }

  function onWheel(ev) {
    if (!isActive()) return;
    if (wheelIsPinchZoom(ev) || (!scrollerCanPan(scrollEl) && wheelLooksLikeMouseWheel(ev))) {
      ev.preventDefault();
      const factor = wheelZoomFactor(ev);
      if (Math.abs(factor - 1) < 1e-6) return;
      zoom.zoomToward(zoom.get() * factor, ev.clientX, ev.clientY, false);
      return;
    }
    if (!scrollerCanPan(scrollEl)) return;
    ev.preventDefault();
    scrollEl.scrollLeft += ev.deltaX;
    scrollEl.scrollTop += ev.deltaY;
  }

  function onPanDown(ev) {
    if (!isActive()) return;
    const middle = ev.button === 1;
    const spaceLeft = spaceDown && ev.button === 0;
    if (!middle && !spaceLeft) return;
    ev.preventDefault();
    ev.stopPropagation();
    pan = {
      x: ev.clientX,
      y: ev.clientY,
      sl: scrollEl.scrollLeft,
      st: scrollEl.scrollTop,
    };
    syncPanClass();
  }

  function onPanMove(ev) {
    if (!pan) return;
    scrollEl.scrollLeft = pan.sl - (ev.clientX - pan.x);
    scrollEl.scrollTop = pan.st - (ev.clientY - pan.y);
  }

  function endPan() {
    if (!pan) return;
    pan = null;
    syncPanClass();
  }

  function onKeyDown(ev) {
    if (ev.code !== "Space" && ev.key !== " ") return;
    if (typingInField(ev) || !isActive()) return;
    ev.preventDefault();
    if (ev.repeat) return;
    spaceDown = true;
    syncPanClass();
  }

  function onKeyUp(ev) {
    if (ev.code !== "Space" && ev.key !== " ") return;
    spaceDown = false;
    if (!pan) syncPanClass();
  }

  function onBlur() {
    spaceDown = false;
    endPan();
    syncPanClass();
  }

  scrollEl.addEventListener("wheel", onWheel, { passive: false });
  canvas.addEventListener("mousedown", onPanDown, true);
  scrollEl.addEventListener("mousedown", onPanDown, true);
  window.addEventListener("mousemove", onPanMove);
  window.addEventListener("mouseup", endPan);
  window.addEventListener("keydown", onKeyDown);
  window.addEventListener("keyup", onKeyUp);
  window.addEventListener("blur", onBlur);
  canvas.addEventListener("auxclick", (ev) => {
    if (ev.button === 1) ev.preventDefault();
  });
  scrollEl.addEventListener("auxclick", (ev) => {
    if (ev.button === 1) ev.preventDefault();
  });
  canvas.addEventListener("contextmenu", (ev) => ev.preventDefault());
  scrollEl.addEventListener("contextmenu", (ev) => ev.preventDefault());

  return {
    isPanning() {
      return Boolean(pan) || spaceDown;
    },
  };
}

function stage2FitBox() {
  const scroll = document.getElementById("stage-scroll");
  const pad = 8;
  let w = scroll ? scroll.clientWidth - pad : 0;
  let h = scroll ? scroll.clientHeight - pad : 0;
  if (w < 80 || h < 80) {
    const chrome = document.querySelector(".stage2-chrome");
    const chromeBottom = chrome ? Math.ceil(chrome.getBoundingClientRect().bottom) : 160;
    const rail =
      document.body.classList.contains("no-exemplars") || document.body.classList.contains("rail-collapsed")
        ? 0
        : 240;
    w = Math.max(120, window.innerWidth - rail - 48);
    h = Math.max(120, window.innerHeight - chromeBottom - 16);
  }
  return { w, h };
}

function stage2DisplayOpts(zoom) {
  const z = zoom && zoom > 0 ? zoom : 1;
  const box = stage2FitBox();
  return {
    targetHeight: Math.max(1, box.h * z),
    maxWidth: Math.max(1, box.w * z),
    maxHeight: Math.max(1, box.h * z),
  };
}

function paintImageWithBoxes(canvas, imageUrl, boxes, opts) {
  const img = new Image();
  img.onload = () => {
    const size = fitDisplaySize(img.width, img.height, opts || popupDisplayOpts());
    canvas.width = size.width;
    canvas.height = size.height;
    const g = canvas.getContext("2d");
    drawImageBright(g, img, 0, 0, canvas.width, canvas.height);
    for (const b of boxes) {
      drawDetectionBox(g, b.bbox, size.scale, {
        status: b.status,
        label: b.label,
        focused: b.focused,
        selected: b.selected,
        kind: b.kind,
        evalKind: b.eval,
        iou: b.iou,
        labelPx: opts && opts.labelPx,
        fnLabels: opts && opts.fnLabels,
        flagged: b.flagged_for_review || b.flagged,
      });
    }
  };
  img.src = imageUrl;
}

function boxLabelFont(kind, opts) {
  const size = opts.labelPx || LABEL_PX;
  if (opts.fnLabels) {
    return kind === "gt"
      ? `bold italic ${size}px sans-serif`
      : `bold ${size}px sans-serif`;
  }
  return `${size}px sans-serif`;
}

function iouCaption(caption, iou) {
  if (typeof iou !== "number" || !(iou > 0)) return caption;
  return `${caption} ${iou.toFixed(2)}`;
}

function drawDetectionBox(ctx, bbox, scale, opts) {
  const status = opts.status;
  const label = opts.label || "";
  const focused = Boolean(opts.focused);
  const selected = Boolean(opts.selected);
  const kind = opts.kind || "detection";
  const evalKind = opts.evalKind || "";
  const labelPx = opts.labelPx || LABEL_PX;
  const [x, y, w, h] = bbox;
  const rx = x * scale;
  const ry = y * scale;
  const rw = w * scale;
  const rh = h * scale;
  ctx.save();
  if (kind === "gt") {
    ctx.strokeStyle = GT_COLOR;
    ctx.fillStyle = GT_COLOR;
    ctx.setLineDash(focused ? [] : [6, 4]);
    ctx.lineWidth = focused ? 5 : 3;
    ctx.globalAlpha = 1;
    ctx.strokeRect(rx, ry, rw, rh);
    ctx.setLineDash([]);
    ctx.font = boxLabelFont(kind, opts);
    const gtTag = evalKind === "fn" ? "FN" : "GT";
    ctx.fillText(iouCaption(`${gtTag}: ${label}`, opts.iou), rx + 2, ry + labelPx);
    if (focused) paintFocusHighlight(ctx, rx, ry, rw, rh);
    ctx.restore();
    return;
  }
  const color = detectionBorderColor(status, label);
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  if (isConfirmed(status)) {
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
    ctx.lineWidth = selected || focused ? 6 : 4;
  } else if (isIncorrect(status)) {
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
    ctx.lineWidth = selected || focused ? 5 : 4;
  } else {
    ctx.setLineDash([8, 5]);
    ctx.globalAlpha = 0.55;
    ctx.lineWidth = selected || focused ? 3 : 2;
  }
  ctx.strokeRect(rx, ry, rw, rh);
  ctx.setLineDash([]);
  ctx.globalAlpha = isInitial(status) ? 0.7 : 1;
  ctx.font = boxLabelFont(kind, opts);
  let caption = label;
  if (evalKind === "tp") caption = `TP: ${label}`;
  else if (evalKind === "fp") caption = `FP: ${label}`;
  else if (evalKind === "fn") caption = `FN: ${label}`;
  else if (isIncorrect(status)) caption = `IGN: ${label}`;
  ctx.fillText(iouCaption(caption, opts.iou), rx + 2, ry + labelPx);
  if (focused) {
    paintFocusHighlight(ctx, rx, ry, rw, rh);
  } else if (selected) {
    ctx.globalAlpha = 1;
    ctx.strokeStyle = SELECTED_COLOR;
    ctx.lineWidth = 2;
    ctx.strokeRect(rx - 2, ry - 2, rw + 4, rh + 4);
  }
  if (opts.flagged) {
    const size = 14;
    ctx.globalAlpha = 1;
    ctx.fillStyle = "#ff1744";
    ctx.save();
    ctx.translate(rx + rw - size - 2, ry + 2);
    ctx.scale(size / 1792, size / 1792);
    ctx.translate(0, 1536);
    ctx.scale(1, -1);
    ctx.fill(new Path2D(FLAG_PATH_FILLED));
    ctx.restore();
  }
  ctx.restore();
}

const BOX_HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
const HANDLE_HIT = 10;
const HANDLE_DRAW = 8;
const MIN_BOX = 4;
const CURSOR_FOR_HANDLE = {
  nw: "nwse-resize",
  se: "nwse-resize",
  ne: "nesw-resize",
  sw: "nesw-resize",
  n: "ns-resize",
  s: "ns-resize",
  e: "ew-resize",
  w: "ew-resize",
};

function clampBbox(bbox, imgW, imgH) {
  let [x, y, w, h] = bbox;
  w = Math.max(MIN_BOX, w);
  h = Math.max(MIN_BOX, h);
  x = Math.min(Math.max(0, x), Math.max(0, imgW - MIN_BOX));
  y = Math.min(Math.max(0, y), Math.max(0, imgH - MIN_BOX));
  w = Math.min(w, imgW - x);
  h = Math.min(h, imgH - y);
  return [x, y, Math.max(MIN_BOX, w), Math.max(MIN_BOX, h)];
}

function handleCenters(bbox, scale) {
  const [x, y, w, h] = bbox;
  const rx = x * scale;
  const ry = y * scale;
  const rw = w * scale;
  const rh = h * scale;
  return {
    nw: [rx, ry],
    n: [rx + rw / 2, ry],
    ne: [rx + rw, ry],
    e: [rx + rw, ry + rh / 2],
    se: [rx + rw, ry + rh],
    s: [rx + rw / 2, ry + rh],
    sw: [rx, ry + rh],
    w: [rx, ry + rh / 2],
  };
}

function hitHandle(px, py, bbox, scale) {
  const centers = handleCenters(bbox, scale);
  for (const name of BOX_HANDLES) {
    const [hx, hy] = centers[name];
    if (Math.abs(px - hx) <= HANDLE_HIT && Math.abs(py - hy) <= HANDLE_HIT) return name;
  }
  return null;
}

function hitBox(imgX, imgY, bbox) {
  const [x, y, w, h] = bbox;
  return imgX >= x && imgX <= x + w && imgY >= y && imgY <= y + h;
}

function boxArea(bbox) {
  return Math.max(0, Number(bbox[2]) || 0) * Math.max(0, Number(bbox[3]) || 0);
}

function distanceToBoxBorder(imgX, imgY, bbox) {
  const [x, y, w, h] = bbox;
  const x2 = x + w;
  const y2 = y + h;
  const inside = imgX >= x && imgX <= x2 && imgY >= y && imgY <= y2;
  if (inside) {
    return Math.min(imgX - x, x2 - imgX, imgY - y, y2 - imgY);
  }
  const dx = imgX < x ? x - imgX : imgX > x2 ? imgX - x2 : 0;
  const dy = imgY < y ? y - imgY : imgY > y2 ? imgY - y2 : 0;
  return Math.hypot(dx, dy);
}

const MOVE_CENTRE_HIT = 16;

/** Centre or near-border of a box (image pixels). Handles are checked separately. */
function hitMoveZone(imgX, imgY, bbox, scale) {
  if (!bbox) return false;
  const [x, y, w, h] = bbox;
  const s = Math.max(scale, 0.001);
  const borderTol = HANDLE_HIT / s;
  if (distanceToBoxBorder(imgX, imgY, bbox) <= borderTol) return true;
  const cap = 0.3 * Math.min(w, h);
  let radius = MOVE_CENTRE_HIT / s;
  if (cap > 0) radius = Math.min(radius, cap);
  return Math.hypot(imgX - (x + w / 2), imgY - (y + h / 2)) <= radius;
}

function applyResize(orig, handle, imgX, imgY, imgW, imgH) {
  let x1 = orig[0];
  let y1 = orig[1];
  let x2 = orig[0] + orig[2];
  let y2 = orig[1] + orig[3];
  if (handle.includes("w")) x1 = imgX;
  if (handle.includes("e")) x2 = imgX;
  if (handle.includes("n")) y1 = imgY;
  if (handle.includes("s")) y2 = imgY;
  return clampBbox(
    [Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1)],
    imgW,
    imgH
  );
}

function drawHandles(ctx, bbox, scale) {
  const centers = handleCenters(bbox, scale);
  ctx.save();
  for (const name of BOX_HANDLES) {
    const [hx, hy] = centers[name];
    ctx.fillStyle = "#fff";
    ctx.strokeStyle = SELECTED_COLOR;
    ctx.lineWidth = 2;
    ctx.fillRect(hx - HANDLE_DRAW / 2, hy - HANDLE_DRAW / 2, HANDLE_DRAW, HANDLE_DRAW);
    ctx.strokeRect(hx - HANDLE_DRAW / 2, hy - HANDLE_DRAW / 2, HANDLE_DRAW, HANDLE_DRAW);
  }
  ctx.restore();
}

function canvasEventPos(canvas, ev) {
  const r = canvas.getBoundingClientRect();
  if (!r.width || !r.height) return { x: 0, y: 0 };
  return {
    x: (ev.clientX - r.left) * (canvas.width / r.width),
    y: (ev.clientY - r.top) * (canvas.height / r.height),
  };
}

/** Server stores naive UTC ISO strings; Date.parse treats those as local time. */
function parseUtcIso(iso) {
  if (!iso) return NaN;
  const s = String(iso).trim();
  if (!s) return NaN;
  if (/[zZ]$/.test(s) || /[+-]\d{2}:\d{2}$/.test(s)) return Date.parse(s);
  return Date.parse(`${s}Z`);
}

/** Avoid resetting a native select while its menu is open — that closes it and can pick an option. */
function setSelectValueIfIdle(select, value) {
  if (!select || value == null || value === "") return;
  if (select === document.activeElement) return;
  if (select.value !== String(value)) select.value = String(value);
}

function applyStageTiming(state, t) {
  if (!t) return;
  const closed =
    typeof t.elapsed_closed_sec === "number" ? t.elapsed_closed_sec : t.elapsed_sec;
  state.elapsedBase = Number(closed) || 0;
  state.running = Boolean(t.running);
  if (state.running) {
    const parsed = parseUtcIso(t.open_start);
    state.startedAt = Number.isFinite(parsed) ? parsed : Date.now();
  } else {
    state.startedAt = null;
  }
}

function saveReviewCursor(payload) {
  api("/api/run/cursor", { method: "POST", body: JSON.stringify(payload) }).catch(() => {});
}

function markStageTourSeen(stage) {
  if (!stage) return;
  const key = stage === "stage2" ? "stage2_tour_seen" : "stage1_tour_seen";
  window.STAGE_TOUR_SEEN = true;
  saveReviewCursor({ [key]: true });
}

function isStageTourSeen() {
  return Boolean(window.STAGE_TOUR_SEEN);
}

function boxScore(box) {
  const s = box && box.score;
  return s == null || s === "" ? 1.0 : Number(s);
}

function formatProb(p) {
  return Number(p).toFixed(1);
}

function syncProbUi(state) {
  const minEl = document.getElementById("prob-min");
  const maxEl = document.getElementById("prob-max");
  const track = document.getElementById("prob-track");
  const label = document.getElementById("prob-range-label");
  if (!minEl || !maxEl) return;
  let minV = Number(minEl.value);
  let maxV = Number(maxEl.value);
  if (minV > maxV) {
    const t = minV;
    minV = maxV;
    maxV = t;
    minEl.value = String(minV);
    maxEl.value = String(maxV);
  }
  state.minProb = minV / 10;
  state.maxProb = maxV / 10;
  if (track) {
    track.style.setProperty("--from", `${minV * 10}%`);
    track.style.setProperty("--span", `${Math.max(0, (maxV - minV) * 10)}%`);
  }
  if (label) {
    label.textContent = `${formatProb(state.minProb)} – ${formatProb(state.maxProb)}`;
  }
  const minAbove = minV > 10 - maxV;
  minEl.style.zIndex = minAbove ? "2" : "1";
  maxEl.style.zIndex = minAbove ? "1" : "2";
}

function bindProbFilter(state, { canEdit, onChange }) {
  const minEl = document.getElementById("prob-min");
  const maxEl = document.getElementById("prob-max");
  if (!minEl || !maxEl) return;
  let timer = null;
  const onInput = () => {
    syncProbUi(state);
    if (typeof canEdit === "function" && !canEdit()) return;
    clearTimeout(timer);
    timer = setTimeout(() => onChange(), 150);
  };
  minEl.addEventListener("input", onInput);
  maxEl.addEventListener("input", onInput);
}

function setProbFilterEnabled(on) {
  const minEl = document.getElementById("prob-min");
  const maxEl = document.getElementById("prob-max");
  if (minEl) minEl.disabled = !on;
  if (maxEl) maxEl.disabled = !on;
}

function updateCountInfo(counts, filter) {
  const loaded = (filter && filter.loaded) || (counts && counts.total);
  const nTotal = loaded != null ? loaded : "—";
  const nConf = (counts && counts.confirmed) || 0;
  const nIgn = (counts && counts.incorrect) || 0;
  let nUnrev = counts && counts.unreviewed;
  if (nUnrev == null && typeof loaded === "number") {
    nUnrev = Math.max(0, loaded - nConf - nIgn);
  }
  const set = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = String(val);
  };
  set("prog-total", nTotal);
  set("prog-confirmed", nConf);
  set("prog-ignored", nIgn);
  set("prog-unreviewed", nUnrev != null ? nUnrev : "—");
}

function bindStageTimerGuards(stage, refreshStatus, isRunning) {
  window.addEventListener("pagehide", () => {
    if (typeof isRunning === "function" ? !isRunning() : !isRunning) return;
    try {
      const blob = new Blob([JSON.stringify({ stage })], { type: "application/json" });
      navigator.sendBeacon("/api/run/stop", blob);
    } catch (_) {}
  });
  window.addEventListener("pageshow", (ev) => {
    if (ev.persisted) refreshStatus();
  });
  document.querySelectorAll('a[href="/stage1"], a[href="/stage2"]').forEach((a) => {
    a.addEventListener("click", async (ev) => {
      const href = a.getAttribute("href");
      if (!href || href === `/${stage}`) return;
      const running = typeof isRunning === "function" ? isRunning() : isRunning;
      if (!running) return;
      ev.preventDefault();
      try {
        await api("/api/run/stop", { method: "POST", body: JSON.stringify({ stage }) });
      } catch (_) {}
      window.location.href = href;
    });
  });
}

function initExemplarRail() {
  const btn = document.getElementById("btn-rail-toggle");
  if (!btn) return;
  const key = "exemplar-rail-collapsed";
  const apply = (collapsed) => {
    document.body.classList.toggle("rail-collapsed", collapsed);
    localStorage.setItem(key, collapsed ? "1" : "0");
    btn.textContent = collapsed ? "›" : "‹";
    btn.setAttribute("aria-label", collapsed ? "Show class examples" : "Hide class examples");
    btn.title = collapsed ? "Show class examples" : "Hide class examples";
  };
  apply(localStorage.getItem(key) === "1");
  btn.addEventListener("click", () => apply(!document.body.classList.contains("rail-collapsed")));
}

let lastPointerClient = { x: 24, y: 24 };
let cursorNoteEl = null;
let cursorNoteTimer = null;

function trackPointerClient(ev) {
  lastPointerClient = { x: ev.clientX, y: ev.clientY };
}

document.addEventListener("pointerdown", trackPointerClient);
document.addEventListener("pointermove", trackPointerClient, { passive: true });

function showCursorNote(text, at) {
  if (!text) return;
  const pos = at || lastPointerClient;
  if (!cursorNoteEl) {
    cursorNoteEl = document.createElement("div");
    cursorNoteEl.className = "cursor-note";
    cursorNoteEl.setAttribute("role", "status");
  }
  const host = document.querySelector("dialog[open]") || document.body;
  if (cursorNoteEl.parentNode !== host) host.appendChild(cursorNoteEl);
  cursorNoteEl.textContent = text;
  cursorNoteEl.style.left = `${pos.x}px`;
  cursorNoteEl.style.top = `${pos.y}px`;
  cursorNoteEl.hidden = false;
  clearTimeout(cursorNoteTimer);
  cursorNoteTimer = setTimeout(() => {
    cursorNoteEl.hidden = true;
  }, 1500);
}

function initReviewCommon() {
  initExemplarRail();
  initBrightnessControl();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initReviewCommon);
} else {
  initReviewCommon();
}
