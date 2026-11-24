"""How a review session is identified in the UI.

Sessions are created by logging in with a tester name and a study (from a
manifest, or synthesised from direct CLI inputs). This module decides what
the page header shows for such a session; templates only render the
``HeaderIdentity`` produced here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping

MANIFEST_SOURCE = "manifest"


@dataclass(frozen=True)
class HeaderField:
    """One labelled header value."""

    label: str
    value: str

    def formatted(self) -> str:
        label = self.label.strip()
        if not label:
            return self.value
        return f"{label}: {self.value}"


@dataclass(frozen=True)
class HeaderIdentity:
    """Fields the study header shows."""

    source: str
    title: HeaderField
    fields: tuple[HeaderField, ...] = ()
    person: str | None = None

    @property
    def detail(self) -> str:
        return " · ".join(field.formatted() for field in self.fields if field.value)


def header_identity(
    session: Mapping[str, Any] | None,
    *,
    progress: Mapping[str, Any],
    dataset_id: str | None = None,
    dataset_n: int | None = None,
) -> HeaderIdentity:
    session = session or {}
    shown = dataset_id if dataset_id is not None else progress.get("current_dataset_id")
    n = dataset_n
    if n is None and progress.get("total") and not progress.get("complete"):
        n = int(progress.get("index") or 0) + 1
    tester = str(session.get("tester") or progress.get("tester") or "")
    title = HeaderField(
        "Study",
        str(progress.get("study_id") or session.get("study_id") or ""),
    )
    fields: list[HeaderField] = []
    if tester:
        fields.append(HeaderField("Tester", tester))
    if shown:
        fields.append(HeaderField("Model", str(shown)))
    total = progress.get("total") or 0
    if n and total:
        fields.append(HeaderField("Model no", f"{n} of {total}"))
    return HeaderIdentity(
        source=MANIFEST_SOURCE,
        title=title,
        fields=tuple(fields),
        person=tester or None,
    )


def stamp_session(
    session: MutableMapping[str, Any],
    source: str,
    *,
    tester: str,
    study_id: str,
    **extra: Any,
) -> None:
    """Write the shared session keys (tester, study, source)."""
    session["source"] = source
    session["tester"] = tester
    session["study_id"] = study_id
    for key, value in extra.items():
        if value is None:
            session.pop(key, None)
        else:
            session[key] = value
