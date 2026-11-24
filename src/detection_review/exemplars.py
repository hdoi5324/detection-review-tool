from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from PIL import Image


def _resolve_image(images_dir: Path, file_name: str) -> Path | None:
    direct = images_dir / file_name
    if direct.is_file():
        return direct
    base = images_dir / Path(file_name).name
    if base.is_file():
        return base
    return None


def build_exemplars(
    *,
    support_coco: Path,
    support_images_dir: Path,
    category_names: list[str],
    k: int = 3,
    cache_dir: Path,
    max_size: int = 360,
) -> dict[str, list[dict[str, Any]]]:
    """Return map category_name -> list of {url, ann_id} for up to K crops."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    coco = json.loads(support_coco.read_text())
    cats = {int(c["id"]): str(c["name"]) for c in coco.get("categories") or []}
    images = {int(im["id"]): im for im in coco.get("images") or []}
    by_name: dict[str, list[dict[str, Any]]] = {n: [] for n in category_names}

    anns = sorted(coco.get("annotations") or [], key=lambda a: int(a["id"]))
    for ann in anns:
        name = cats.get(int(ann["category_id"]))
        if name is None or name not in by_name:
            continue
        if len(by_name[name]) >= k:
            continue
        im = images.get(int(ann["image_id"]))
        if im is None:
            continue
        img_path = _resolve_image(support_images_dir, im["file_name"])
        if img_path is None:
            continue
        out_name = f"{name.replace(' ', '_')}__{ann['id']}__s{max_size}.jpg"
        out_path = cache_dir / out_name
        if not out_path.is_file():
            try:
                _write_crop(img_path, ann["bbox"], out_path, max_size=max_size)
            except Exception:
                continue
        by_name[name].append(
            {
                "ann_id": int(ann["id"]),
                "url": f"/api/exemplars/file/{out_name}",
                "label": name,
            }
        )
    return by_name


def _write_crop(image_path: Path, bbox: list[float], out_path: Path, max_size: int) -> None:
    x, y, w, h = [float(v) for v in bbox]
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        W, H = im.size
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(W, int(x + w))
        y1 = min(H, int(y + h))
        if x1 <= x0 or y1 <= y0:
            raise ValueError("empty crop")
        crop = im.crop((x0, y0, x1, y1))
        crop.thumbnail((max_size, max_size))
        crop.save(out_path, format="JPEG", quality=85)


def _write_crop_fixed_height(
    image_path: Path,
    bbox: list[float],
    out_path: Path,
    height: int,
    max_width: int = 2400,
) -> None:
    """Crop the bbox and scale so height is fixed; width follows aspect."""
    x, y, w, h = [float(v) for v in bbox]
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        W, H = im.size
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(W, int(x + w))
        y1 = min(H, int(y + h))
        if x1 <= x0 or y1 <= y0:
            raise ValueError("empty crop")
        crop = im.crop((x0, y0, x1, y1))
        cw, ch = crop.size
        out_h = max(1, int(height))
        out_w = max(1, round(out_h * cw / ch))
        if out_w > max_width:
            out_w = max_width
            out_h = max(1, round(max_width * ch / cw))
        if (cw, ch) != (out_w, out_h):
            crop = crop.resize((out_w, out_h), Image.Resampling.LANCZOS)
        crop.save(out_path, format="JPEG", quality=85)


def write_detection_thumb(
    image_path: Path,
    bbox: list[float],
    out_path: Path,
    max_size: int = 420,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not out_path.is_file():
        _write_crop_fixed_height(image_path, bbox, out_path, height=max_size)
    return out_path


def image_bytes(path: Path, max_edge: int | None = None) -> bytes:
    with Image.open(path) as im:
        im = im.convert("RGB")
        if max_edge:
            im.thumbnail((max_edge, max_edge))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
