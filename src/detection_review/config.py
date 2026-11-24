from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def load_project_env() -> None:
    """Load `.env` from the working directory and the repo root (does not override existing env)."""
    from dotenv import load_dotenv

    load_dotenv()
    repo_env = Path(__file__).resolve().parents[2] / ".env"
    if repo_env.is_file():
        load_dotenv(repo_env)


def _as_str_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ValueError(f"{field_name} must be a string or list of strings")


@dataclass
class TourStep:
    """One step in a passive UI walkthrough."""

    target: str
    title: str
    body: str
    demo: str = ""
    placement: str = ""
    targets: list[str] = field(default_factory=list)

    def validate(self, field_name: str) -> None:
        selectors = self.selector_list()
        if not selectors:
            raise ValueError(f"{field_name} must have target or targets")
        if not str(self.title).strip():
            raise ValueError(f"{field_name}.title must be non-empty")
        if not str(self.body).strip():
            raise ValueError(f"{field_name}.body must be non-empty")
        if self.placement and self.placement not in ("top", "bottom", "left", "right"):
            raise ValueError(f"{field_name}.placement must be top, bottom, left, or right")

    def selector_list(self) -> list[str]:
        if self.targets:
            return [s for s in self.targets if str(s).strip()]
        if str(self.target).strip():
            return [str(self.target).strip()]
        return []


def _parse_tour_steps(raw: Any, field_name: str) -> list[TourStep]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{field_name} must be a list of tour steps")
    steps: list[TourStep] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{field_name}[{i}] must be an object")
        targets_raw = item.get("targets") or []
        targets = (
            [str(t).strip() for t in targets_raw if str(t).strip()]
            if isinstance(targets_raw, list)
            else []
        )
        target = str(item.get("target") or "").strip()
        if not target and targets:
            target = targets[0]
        step = TourStep(
            target=target,
            title=str(item.get("title") or "").strip(),
            body=str(item.get("body") or "").strip(),
            demo=str(item.get("demo") or "").strip(),
            placement=str(item.get("placement") or "").strip(),
            targets=targets,
        )
        step.validate(f"{field_name}[{i}]")
        steps.append(step)
    return steps


@dataclass
class StageIntro:
    """On-screen instructions shown before the tester presses Start."""

    paragraphs: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    hint: str = "Press Start to begin this stage."

    def validate(self) -> None:
        if not isinstance(self.hint, str):
            raise ValueError("stage intro hint must be a string")

    @classmethod
    def from_raw(cls, raw: Any, field_name: str = "stage1_intro") -> "StageIntro":
        if raw is None:
            return cls()
        if isinstance(raw, (str, list)):
            intro = cls(paragraphs=_as_str_list(raw, field_name))
            intro.validate()
            return intro
        if not isinstance(raw, dict):
            raise ValueError(
                f"{field_name} must be a string, list of strings, or "
                "object with paragraphs/tasks/hint"
            )
        intro = cls(
            paragraphs=_as_str_list(raw.get("paragraphs", raw.get("body")), f"{field_name}.paragraphs"),
            tasks=_as_str_list(raw.get("tasks"), f"{field_name}.tasks"),
            hint=str(raw.get("hint", cls.hint)),
        )
        intro.validate()
        return intro


@dataclass
class ReviewConfig:
    """Filters and UI defaults for a study."""

    stage1_top_n: int = 100
    stage1_min_score: float = 0.05
    stage1_intro: StageIntro = field(default_factory=StageIntro)
    stage2_intro: StageIntro = field(default_factory=StageIntro)
    stage1_tour: list[TourStep] = field(default_factory=list)
    stage2_tour: list[TourStep] = field(default_factory=list)

    def validate(self) -> None:
        if self.stage1_top_n < 1:
            raise ValueError("stage1_top_n must be >= 1")
        if not (0.0 <= self.stage1_min_score <= 1.0):
            raise ValueError("stage1_min_score must be in [0, 1]")
        self.stage1_intro.validate()
        self.stage2_intro.validate()
        for i, step in enumerate(self.stage1_tour):
            step.validate(f"stage1_tour[{i}]")
        for i, step in enumerate(self.stage2_tour):
            step.validate(f"stage2_tour[{i}]")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "ReviewConfig":
        raw = raw or {}
        cfg = cls(
            stage1_top_n=int(raw.get("stage1_top_n", raw.get("top_n", 100))),
            stage1_min_score=float(raw.get("stage1_min_score", raw.get("min_score", 0.05))),
            stage1_intro=StageIntro.from_raw(raw.get("stage1_intro"), "stage1_intro"),
            stage2_intro=StageIntro.from_raw(raw.get("stage2_intro"), "stage2_intro"),
            stage1_tour=_parse_tour_steps(raw.get("stage1_tour"), "stage1_tour"),
            stage2_tour=_parse_tour_steps(raw.get("stage2_tour"), "stage2_tour"),
        )
        cfg.validate()
        return cfg

    @classmethod
    def load(cls, path: Path | None, manifest_settings: dict[str, Any] | None = None) -> "ReviewConfig":
        """Load config file, then overlay optional manifest.settings."""
        data: dict[str, Any] = {}
        if path is not None:
            path = path.resolve()
            if not path.is_file():
                raise FileNotFoundError(f"config not found: {path}")
            data.update(json.loads(path.read_text()))
        if manifest_settings:
            data.update(manifest_settings)
        return cls.from_dict(data)
