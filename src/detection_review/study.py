from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class DatasetSpec:
    id: str
    images_dir: Path
    predictions_coco: Path
    support_coco: Path | None = None
    support_images_dir: Path | None = None
    ground_truth_coco: Path | None = None

    def resolve(self, base: Path | None = None) -> "DatasetSpec":
        def r(p: Path | None) -> Path | None:
            if p is None:
                return None
            if p.is_absolute():
                return p
            if base is None:
                return p.resolve()
            return (base / p).resolve()

        return DatasetSpec(
            id=self.id,
            images_dir=r(self.images_dir) or Path(self.images_dir),
            predictions_coco=r(self.predictions_coco) or Path(self.predictions_coco),
            support_coco=r(self.support_coco),
            support_images_dir=r(self.support_images_dir),
            ground_truth_coco=r(self.ground_truth_coco),
        )

    def validate(self) -> None:
        required: list[tuple[str, Path, bool]] = [
            ("images_dir", self.images_dir, True),
            ("predictions_coco", self.predictions_coco, False),
        ]
        if self.support_coco is not None or self.support_images_dir is not None:
            if self.support_coco is None or self.support_images_dir is None:
                raise FileNotFoundError("support_coco and support_images_dir must be set together")
            required.append(("support_coco", self.support_coco, False))
            required.append(("support_images_dir", self.support_images_dir, True))
        for label, path, is_dir in required:
            if is_dir and not path.is_dir():
                raise FileNotFoundError(f"{label} not a directory: {path}")
            if not is_dir and not path.is_file():
                raise FileNotFoundError(f"{label} not a file: {path}")
        if self.ground_truth_coco is not None and not self.ground_truth_coco.is_file():
            raise FileNotFoundError(f"ground_truth_coco not a file: {self.ground_truth_coco}")


@dataclass
class StudyManifest:
    study_id: str
    datasets: list[DatasetSpec]
    settings: dict[str, Any] | None = None
    source_path: Path | None = None

    @classmethod
    def load(cls, path: Path) -> "StudyManifest":
        path = path.resolve()
        raw: dict[str, Any] = json.loads(path.read_text())
        base = path.parent
        datasets = []
        for d in raw["datasets"]:
            spec = DatasetSpec(
                id=d["id"],
                images_dir=Path(d["images_dir"]),
                predictions_coco=Path(d["predictions_coco"]),
                support_coco=Path(d["support_coco"]) if d.get("support_coco") else None,
                support_images_dir=Path(d["support_images_dir"]) if d.get("support_images_dir") else None,
                ground_truth_coco=Path(d["ground_truth_coco"]) if d.get("ground_truth_coco") else None,
            ).resolve(base)
            spec.validate()
            datasets.append(spec)
        if not datasets:
            raise ValueError("manifest has no datasets")
        return cls(
            study_id=raw["study_id"],
            datasets=datasets,
            settings=raw.get("settings") if isinstance(raw.get("settings"), dict) else None,
            source_path=path,
        )

    def __len__(self) -> int:
        return len(self.datasets)


def manifest_from_inputs(
    *,
    study_id: str = "review",
    dataset_id: str = "dataset",
    images_dir: Path,
    predictions_coco: Path,
    support_coco: Path | None = None,
    support_images_dir: Path | None = None,
    ground_truth_coco: Path | None = None,
) -> StudyManifest:
    """Build a one-dataset study directly from CLI inputs (no manifest file)."""
    spec = DatasetSpec(
        id=dataset_id,
        images_dir=Path(images_dir),
        predictions_coco=Path(predictions_coco),
        support_coco=Path(support_coco) if support_coco else None,
        support_images_dir=(
            Path(support_images_dir)
            if support_images_dir
            else (Path(images_dir) if support_coco else None)
        ),
        ground_truth_coco=Path(ground_truth_coco) if ground_truth_coco else None,
    ).resolve()
    spec.validate()
    return StudyManifest(study_id=study_id, datasets=[spec])


def peek_study_id(path: Path) -> str:
    """Read study_id from a manifest without resolving dataset paths."""
    path = path.resolve()
    raw: dict[str, Any] = json.loads(path.read_text())
    study_id = raw.get("study_id")
    if not isinstance(study_id, str) or not study_id.strip():
        raise ValueError(f"{path} has no study_id")
    return study_id.strip()


def list_manifests(directory: Path) -> dict[str, Path]:
    """Map study_id -> path for *.json in a machine folder (skips review_config.json)."""
    directory = directory.resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"manifest directory not found: {directory}")
    catalog: dict[str, Path] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name == "review_config.json":
            continue
        study_id = peek_study_id(path)
        if study_id in catalog:
            raise ValueError(f"duplicate study_id {study_id!r} in {catalog[study_id]} and {path}")
        catalog[study_id] = path
    if not catalog:
        raise ValueError(f"no study manifests in {directory}")
    return catalog


def build_catalog(
    *,
    manifest: Path | None = None,
    manifest_dir: Path | None = None,
) -> tuple[dict[str, Path], str | None]:
    """Return (study_id -> path, locked study_id when a single --manifest is used)."""
    if manifest is None and manifest_dir is None:
        raise ValueError("provide --manifest or --manifest-dir")
    catalog: dict[str, Path] = {}
    locked: str | None = None
    if manifest_dir is not None:
        catalog.update(list_manifests(manifest_dir))
    if manifest is not None:
        path = manifest.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"manifest not found: {path}")
        locked = peek_study_id(path)
        if locked in catalog and catalog[locked] != path:
            raise ValueError(
                f"study_id {locked!r} already mapped to {catalog[locked]}, not {path}"
            )
        catalog[locked] = path
    return catalog, locked
