/** Passive spotlight tour: dim overlay, rectangular highlight, floating tooltip. */
const TOUR_PAD = 8;
const TOUR_Z = 50;

let activeTour = null;

function createTour(steps, hooks) {
  const h = hooks || {};
  let index = 0;
  let running = false;
  let overlay = null;
  let spotlight = null;
  let tooltip = null;
  let host = document.body;
  let onResize = null;
  let onKey = null;

  function stepCount() {
    return (steps && steps.length) || 0;
  }

  function currentStep() {
    return steps[index];
  }

  function stepSelectors(step) {
    if (step.targets && step.targets.length) return step.targets;
    if (step.target) return [step.target];
    return [];
  }

  function resolveElements(step) {
    if (step.demo === "selectOne") {
      const demo = document.querySelector(".patch-card.tour-demo");
      if (demo) return [demo];
    }
    const selectors = stepSelectors(step);
    if (selectors.some((sel) => sel.includes("expand-btn"))) {
      const scroller = document.getElementById("stage-scroll");
      const sr = scroller ? scroller.getBoundingClientRect() : null;
      const btns = [];
      for (const sel of selectors) {
        try {
          document.querySelectorAll(sel).forEach((el) => btns.push(el));
        } catch (_) {}
      }
      const visible = btns.find((btn) => {
        const r = btn.getBoundingClientRect();
        if (!(r.width > 0) || !(r.height > 0)) return false;
        if (!sr) return true;
        return r.bottom > sr.top + 8 && r.top < sr.bottom - 8;
      });
      if (visible) return [visible];
      if (btns[0]) return [btns[0]];
    }
    const els = [];
    if (step.targets && step.targets.length) {
      for (const sel of step.targets) {
        try {
          document.querySelectorAll(sel).forEach((el) => els.push(el));
        } catch (_) {}
      }
      return els;
    }
    if (step.target) {
      try {
        const el = document.querySelector(step.target);
        if (el) els.push(el);
      } catch (_) {}
    }
    return els;
  }

  function resolveTarget(step) {
    const els = resolveElements(step);
    return els.length ? els[0] : null;
  }

  function isFormControlActive() {
    const ae = document.activeElement;
    if (!ae) return false;
    const tag = ae.tagName;
    return tag === "SELECT" || tag === "INPUT" || tag === "TEXTAREA";
  }

  function topInsetPx() {
    const topbar = document.querySelector(".topbar");
    return topbar ? topbar.getBoundingClientRect().bottom + 8 : 8;
  }

  function scrollTourTarget(el) {
    const card = el.closest(".patch-card");
    const scrollEl = card || el;
    const scroller = scrollEl.closest(".stage-scroll");
    const er = scrollEl.getBoundingClientRect();
    if (scroller) {
      const sr = scroller.getBoundingClientRect();
      const fullyVisible = er.top >= sr.top && er.bottom <= sr.bottom && er.left >= sr.left && er.right <= sr.right;
      if (!fullyVisible) {
        scrollEl.scrollIntoView({ block: "nearest", inline: "nearest" });
      }
      return;
    }
    const vh = window.innerHeight;
    const vw = window.innerWidth;
    const fullyVisible = er.top >= 0 && er.bottom <= vh && er.left >= 0 && er.right <= vw;
    if (!fullyVisible) {
      scrollEl.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }

  function measureViewportRect(step, allowScroll) {
    const els = resolveElements(step);
    if (!els.length) return null;
    if (allowScroll) scrollTourTarget(els[0]);
    let top = Infinity;
    let left = Infinity;
    let bottom = -Infinity;
    let right = -Infinity;
    for (const el of els) {
      const r = el.getBoundingClientRect();
      if (!(r.width > 0) || !(r.height > 0)) continue;
      top = Math.min(top, r.top);
      left = Math.min(left, r.left);
      bottom = Math.max(bottom, r.bottom);
      right = Math.max(right, r.right);
    }
    if (!Number.isFinite(top)) return null;
    const pad = typeof step.padding === "number" ? step.padding : TOUR_PAD;
    return {
      top: top - pad,
      left: left - pad,
      width: right - left + pad * 2,
      height: bottom - top + pad * 2,
    };
  }

  function hostRectCoords(viewportRect) {
    if (host === document.body) return viewportRect;
    const hostRect = host.getBoundingClientRect();
    return {
      top: viewportRect.top - hostRect.top,
      left: viewportRect.left - hostRect.left,
      width: viewportRect.width,
      height: viewportRect.height,
    };
  }

  function setHost(nextHost) {
    if (nextHost === host) return;
    host = nextHost || document.body;
    if (overlay && overlay.parentNode !== host) host.appendChild(overlay);
    if (spotlight && spotlight.parentNode !== host) host.appendChild(spotlight);
    if (tooltip && tooltip.parentNode !== host) host.appendChild(tooltip);
  }

  function clipRectToViewport(rect) {
    const margin = 8;
    const maxBottom = window.innerHeight - margin;
    const maxRight = window.innerWidth - margin;
    const top = Math.max(rect.top, margin);
    const left = Math.max(rect.left, margin);
    const bottom = Math.min(rect.top + rect.height, maxBottom);
    const right = Math.min(rect.left + rect.width, maxRight);
    return {
      top,
      left,
      width: Math.max(1, right - left),
      height: Math.max(1, bottom - top),
    };
  }

  function layoutRect(viewportRect) {
    return clipRectToViewport(viewportRect);
  }

  function pickHost(step) {
    const el = resolveTarget(step);
    const dlg = el && el.closest("dialog[open]");
    setHost(dlg || document.body);
  }

  function rectsOverlap(a, b, gap) {
    const g = gap || 0;
    return !(
      a.left + a.width + g <= b.left ||
      b.left + b.width + g <= a.left ||
      a.top + a.height + g <= b.top ||
      b.top + b.height + g <= a.top
    );
  }

  function positionTooltip(viewportRect, step) {
    const margin = 12;
    const tipRect = tooltip.getBoundingClientRect();
    const minTop = topInsetPx();
    const minLeft = margin;
    const maxTop = window.innerHeight - margin;
    const maxLeft = window.innerWidth - margin;
    const alignTop = viewportRect.top;
    const targetMidX = viewportRect.left + viewportRect.width / 2;
    const targetOnRight = targetMidX > window.innerWidth * 0.45;

    function clamp(top, left) {
      return {
        top: Math.max(minTop, Math.min(top, maxTop - tipRect.height)),
        left: Math.max(minLeft, Math.min(left, maxLeft - tipRect.width)),
      };
    }

    function visibleArea(top, left) {
      const t = Math.max(top, minTop);
      const l = Math.max(left, minLeft);
      const b = Math.min(top + tipRect.height, maxTop);
      const r = Math.min(left + tipRect.width, maxLeft);
      return Math.max(0, b - t) * Math.max(0, r - l);
    }

    const spaceRight = maxLeft - (viewportRect.left + viewportRect.width);
    const spaceLeft = viewportRect.left - minLeft;
    const canRight = spaceRight >= tipRect.width + margin;
    const canLeft = spaceLeft >= tipRect.width + margin;

    const order = [];
    const pref = step.placement;
    if (pref) order.push(pref);
    if (targetOnRight) {
      if (canLeft && !order.includes("left")) order.push("left");
      if (canRight && !order.includes("right")) order.push("right");
    } else {
      if (canRight && !order.includes("right")) order.push("right");
      if (canLeft && !order.includes("left")) order.push("left");
    }
    if (!order.includes("left")) order.push("left");
    if (!order.includes("right")) order.push("right");
    order.push("top", "bottom");

    const variants = {
      right: {
        top: alignTop,
        left: viewportRect.left + viewportRect.width + margin,
      },
      left: {
        top: alignTop,
        left: viewportRect.left - tipRect.width - margin,
      },
      top: {
        top: alignTop - tipRect.height - margin,
        left: viewportRect.left,
      },
      bottom: {
        top: alignTop + viewportRect.height + margin,
        left: viewportRect.left,
      },
    };

    const sideBonus = targetOnRight
      ? { left: 9000, right: 2000, top: 800, bottom: 0 }
      : { right: 8000, left: 7500, top: 800, bottom: 0 };
    let best = clamp(variants.left.top, variants.left.left);
    let bestScore = -Infinity;

    for (const place of order) {
      const pos = variants[place];
      if (!pos) continue;
      const c = clamp(pos.top, pos.left);
      const tipBox = { top: c.top, left: c.left, width: tipRect.width, height: tipRect.height };
      const overlapPenalty = rectsOverlap(tipBox, viewportRect, 8) ? 200000 : 0;
      const topAlignPenalty = Math.abs(c.top - alignTop) * 40;
      const score =
        visibleArea(c.top, c.left) + (sideBonus[place] || 0) - topAlignPenalty - overlapPenalty;
      if (score > bestScore) {
        bestScore = score;
        best = c;
      }
    }

    if (host === document.body) {
      tooltip.style.position = "fixed";
      tooltip.style.top = `${best.top}px`;
      tooltip.style.left = `${best.left}px`;
    } else {
      const hostRect = host.getBoundingClientRect();
      tooltip.style.position = "absolute";
      tooltip.style.top = `${best.top - hostRect.top}px`;
      tooltip.style.left = `${best.left - hostRect.left}px`;
    }
  }

  function applyLayout(opts) {
    if (!running) return;
    if (isFormControlActive()) return;
    const step = currentStep();
    if (!step) return;
    pickHost(step);
    const viewportRect = measureViewportRect(step, Boolean(opts && opts.scroll));
    if (!viewportRect) {
      spotlight.hidden = true;
      tooltip.style.position = "fixed";
      tooltip.style.top = "50%";
      tooltip.style.left = "50%";
      tooltip.style.transform = "translate(-50%, -50%)";
      return;
    }
    const layout = layoutRect(viewportRect);
    const rect = hostRectCoords(layout);
    spotlight.hidden = false;
    tooltip.style.transform = "";
    if (host === document.body) {
      spotlight.style.position = "fixed";
      spotlight.style.top = `${layout.top}px`;
      spotlight.style.left = `${layout.left}px`;
    } else {
      spotlight.style.position = "absolute";
      spotlight.style.top = `${rect.top}px`;
      spotlight.style.left = `${rect.left}px`;
    }
    spotlight.style.width = `${layout.width}px`;
    spotlight.style.height = `${layout.height}px`;
    positionTooltip(layout, step);
  }

  function scheduleLayout(opts) {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => applyLayout(opts));
    });
  }

  function renderTooltip(step, i) {
    const n = stepCount();
    const isFirst = i <= 0;
    const isLast = i >= n - 1;
    tooltip.innerHTML = `
      <div class="tour-tooltip-head">
        <strong class="tour-tooltip-title">${escapeHtml(step.title || "")}</strong>
        <span class="tour-tooltip-progress">${i + 1} / ${n}</span>
      </div>
      <p class="tour-tooltip-body">${escapeHtml(step.body || "")}</p>
      <div class="tour-tooltip-actions">
        <button type="button" class="ghost tour-btn-back" ${isFirst ? "disabled" : ""}>Back</button>
        <button type="button" class="ghost tour-btn-skip">Skip tour</button>
        <button type="button" class="primary tour-btn-next">${isLast ? "Finish" : "Next"}</button>
      </div>`;
    tooltip.querySelector(".tour-btn-back").addEventListener("click", () => go(-1));
    tooltip.querySelector(".tour-btn-skip").addEventListener("click", () => finish(true));
    tooltip.querySelector(".tour-btn-next").addEventListener("click", () => (isLast ? finish(false) : go(1)));
    tooltip.querySelector(".tour-btn-next").focus();
    scheduleLayout({ scroll: true });
  }

  function go(delta) {
    const prev = index;
    if (h.onLeave) h.onLeave(steps[prev], prev);
    index = Math.max(0, Math.min(stepCount() - 1, index + delta));
    const step = currentStep();
    if (h.onEnter) {
      const ret = h.onEnter(step, index);
      if (ret && typeof ret.then === "function") {
        ret.then(() => renderTooltip(step, index)).catch(() => renderTooltip(step, index));
        return;
      }
    }
    renderTooltip(step, index);
  }

  function buildDom() {
    overlay = document.createElement("div");
    overlay.className = "tour-overlay";
    spotlight = document.createElement("div");
    spotlight.className = "tour-spotlight";
    spotlight.setAttribute("aria-hidden", "true");
    tooltip = document.createElement("div");
    tooltip.className = "tour-tooltip";
    tooltip.setAttribute("role", "dialog");
    tooltip.setAttribute("aria-modal", "true");
    host = document.body;
    host.appendChild(overlay);
    host.appendChild(spotlight);
    host.appendChild(tooltip);
    document.body.classList.add("tour-active");

    onResize = () => scheduleLayout({ scroll: false });
    onKey = (ev) => {
      if (!running) return;
      if (ev.key === "Escape") {
        ev.preventDefault();
        finish(true);
      } else if (ev.key === "ArrowRight" || ev.key === "Enter") {
        ev.preventDefault();
        if (index >= stepCount() - 1) finish(false);
        else go(1);
      } else if (ev.key === "ArrowLeft") {
        ev.preventDefault();
        if (index > 0) go(-1);
      }
    };
    window.addEventListener("resize", onResize);
    document.addEventListener("keydown", onKey);
  }

  function teardownDom() {
    document.body.classList.remove("tour-active");
    window.removeEventListener("resize", onResize);
    document.removeEventListener("keydown", onKey);
    overlay?.remove();
    spotlight?.remove();
    tooltip?.remove();
    overlay = null;
    spotlight = null;
    tooltip = null;
    host = document.body;
  }

  function finish(skipped) {
    if (!running) return;
    const prev = index;
    if (h.onLeave) h.onLeave(steps[prev], prev);
    running = false;
    teardownDom();
    if (h.onFinish) h.onFinish({ skipped, index: prev });
    if (activeTour === api) activeTour = null;
  }

  function start() {
    if (!stepCount()) return false;
    if (running) finish(true);
    index = 0;
    running = true;
    activeTour = api;
    buildDom();
    const step = currentStep();
    if (h.onEnter) {
      const ret = h.onEnter(step, index);
      if (ret && typeof ret.then === "function") {
        ret.then(() => renderTooltip(step, index)).catch(() => renderTooltip(step, index));
        return true;
      }
    }
    renderTooltip(step, index);
    return true;
  }

  function stop() {
    finish(true);
  }

  const api = {
    start,
    stop,
    restart() {
      stop();
      start();
    },
    isRunning() {
      return running;
    },
  };
  return api;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showTourStartHint(show) {
  const el = document.getElementById("tour-start-hint");
  if (!el) return;
  el.hidden = !show;
}

/** Register stage tour starter; called from stage1.js / stage2.js after load. */
function registerStageTour(starter) {
  window.restartStageTour = () => {
    showTourStartHint(false);
    if (typeof starter === "function") starter(true);
  };
  initTourHelpButton();
}

function initTourHelpButton() {
  const btn = document.getElementById("btn-help");
  if (!btn || btn.dataset.tourBound === "1") return;
  btn.dataset.tourBound = "1";
  btn.addEventListener("click", () => {
    if (typeof window.restartStageTour === "function") window.restartStageTour();
  });
}
