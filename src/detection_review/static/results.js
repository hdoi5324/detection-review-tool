const grid = document.getElementById("fn-grid");
const fnInfo = document.getElementById("fn-info");
const contextDialog = document.getElementById("context-dialog");

function resultsCompareQuery() {
  const compare = window.RESULTS_COMPARE;
  return compare ? `?compare=${encodeURIComponent(compare)}` : "";
}

function overlayBoxes(ctx) {
  const dets = (ctx.reviewed_boxes || []).map((b) => ({
    ...b,
    kind: b.kind || "detection",
  }));
  return sortBoxesImageOrder([...(ctx.gt_boxes || []), ...dets]);
}

async function openFnContext(fnId) {
  const ctx = await api(`/api/results/fns/${fnId}/context${resultsCompareQuery()}`);
  const fnLabel = ctx.fn?.label || "";
  document.getElementById("ctx-title").textContent =
    `${ctx.file_name} — FN ${ctx.fn?.id ?? fnId}${fnLabel ? ` (${fnLabel})` : ""}`;
  paintImageWithBoxes(
    document.getElementById("ctx-canvas"),
    ctx.image_url,
    overlayBoxes(ctx),
    { ...popupDisplayOpts(), fnLabels: true, labelPx: 18 }
  );
  if (!contextDialog.open) contextDialog.showModal();
}

function renderFnCard(item) {
  const card = document.createElement("div");
  card.className = "patch-card fn";
  card.dataset.id = String(item.id);
  card.style.setProperty("--class-color", classColor(item.label));
  card.style.setProperty("--thumb-aspect", String(thumbAspect(item.bbox)));
  card.innerHTML = `
      <div class="thumb-wrap">
        <img loading="lazy" src="${item.thumb_url}" alt="${item.label}" />
        ${expandButtonHtml("Open full image with GT and verified boxes")}
      </div>
      <div class="patch-meta">
        <div class="meta-top">
          <span class="badge incorrect">FN</span>
        </div>
        <div class="meta-label">${item.label}</div>
        <div class="muted fn-file">${item.file_name}</div>
        ${
          typeof item.best_iou === "number" && item.best_iou > 0
            ? `<div class="muted">best IoU ${item.best_iou.toFixed(2)}</div>`
            : ""
        }
      </div>`;
  card.title = `Missed ${item.label} — open full image`;
  const open = (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    openFnContext(item.id).catch((e) => {
      if (fnInfo) fnInfo.textContent = e.message;
    });
  };
  card.addEventListener("click", open);
  card.querySelector(".expand-btn").addEventListener("click", open);
  return card;
}

async function loadFalseNegatives() {
  if (!window.HAS_GT || !grid) return;
  const data = await api(`/api/results/fns${resultsCompareQuery()}`);
  if (!data.has_gt) {
    fnInfo.textContent = "No ground truth for this model.";
    return;
  }
  if (!data.items.length) {
    fnInfo.textContent = "No false negatives — every ground-truth box was matched.";
    return;
  }
  fnInfo.textContent = `${data.total} missed box${data.total === 1 ? "" : "es"}`;
  grid.innerHTML = "";
  for (const item of data.items) grid.appendChild(renderFnCard(item));
}

if (window.HAS_GT) {
  loadFalseNegatives().catch((e) => {
    if (fnInfo) fnInfo.textContent = e.message;
  });
}
