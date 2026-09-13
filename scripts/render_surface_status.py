"""Render a read-only BMAD status roll-up from registered repositories."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

import yaml


ALLOWED_STATUSES = {
    "backlog",
    "ready-for-dev",
    "in-progress",
    "review",
    "done",
}
META_KEY_PATTERNS = (
    re.compile(r"^epic-"),
    re.compile(r"-retrospective$"),
    re.compile(r"^retrospective-"),
    re.compile(r"^action[_-]"),
)
MARKDOWN_STORY_ROW = re.compile(
    r"^\|\s*`(?P<id>[^`]+)`\s*\|\s*(?P<surface>[^|]+?)\s*\|\s*(?P<title>.*?)\s*\|\s*$"
)


class SurfaceStatusError(ValueError):
    """Raised when a repository's local BMAD records cannot be joined."""

    def __init__(self, issues: str | Iterable[str]):
        if isinstance(issues, str):
            normalized = [issues]
        else:
            normalized = list(issues)
        self.issues = normalized
        super().__init__("; ".join(normalized))


@dataclass(frozen=True)
class StoryRecord:
    repository: str
    surface: str
    story_id: str
    status: str
    title: str
    kind: str
    spec: str | None
    validation: str | None


@dataclass(frozen=True)
class RepositoryReport:
    repository: str
    applicable: bool
    records: tuple[StoryRecord, ...]
    note: str | None = None


def _load_yaml(path: Path) -> dict:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SurfaceStatusError(f"missing file: {path.name}") from exc
    except yaml.YAMLError as exc:
        raise SurfaceStatusError(f"invalid YAML in {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise SurfaceStatusError(f"YAML root must be a mapping: {path.name}")
    return value


def _repo_relative(root: Path, raw: object, field: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise SurfaceStatusError(f"{field} must be a repository-relative path")
    path = Path(raw)
    if path.is_absolute():
        raise SurfaceStatusError(f"{field} must not be absolute: {raw}")
    return root / path


def _status_key_map(statuses: dict[object, object]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for raw_key, raw_status in statuses.items():
        key = str(raw_key)
        if any(pattern.search(key) for pattern in META_KEY_PATTERNS):
            continue
        normalized = key.casefold()
        if normalized in result:
            raise SurfaceStatusError(f"duplicate tracker story ID: {key}")
        result[normalized] = (key, str(raw_status))
    return result


def _surface_name(raw: object, default: str) -> str:
    if raw is None:
        return default
    text = str(raw).strip()
    lowered = text.casefold()
    if "tui" in lowered:
        return "T"
    if "puck" in lowered:
        return "P"
    if "esp32" in lowered or "touch display" in lowered:
        return "E"
    if "w/k" in lowered or "web" in lowered or "ipad" in lowered:
        return "W/K"
    if "android" in lowered:
        return "A"
    if "ios" in lowered:
        return "I"
    return text


def _surface_from_story_id(story_id: str, defaults: Sequence[str]) -> str:
    parts = story_id.casefold().split("-")
    if len(parts) >= 2:
        marker = parts[1]
        if marker == "wk":
            return "W/K"
        if marker in {"t", "p", "e", "i", "a"}:
            return marker.upper()
    return defaults[0] if defaults else "?"


def _markdown_catalog(path: Path) -> dict[str, tuple[str, str]]:
    catalog: dict[str, tuple[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = MARKDOWN_STORY_ROW.match(line)
        if not match:
            continue
        story_id = match.group("id").strip()
        normalized = story_id.casefold()
        if normalized in catalog:
            raise SurfaceStatusError(f"duplicate story ID in story index: {story_id}")
        catalog[normalized] = (
            _surface_name(match.group("surface"), "T"),
            match.group("title").strip(),
        )
    return catalog


def _catalog_lookup(
    catalog: dict[str, tuple[str, str]], story_id: str
) -> tuple[str, str] | None:
    candidates = [story_id.casefold()]
    shortened = re.sub(r"^[0-9]+-", "", story_id.casefold())
    if shortened != story_id.casefold():
        candidates.append(shortened)
    parts = story_id.casefold().split("-")
    if len(parts) >= 3 and parts[1] in {"t", "p", "e", "wk"}:
        candidates.insert(1, f"{parts[0]}-{parts[1]}-{parts[2]}")
        candidates.append(f"{parts[1]}-{parts[2]}")
    for candidate in candidates:
        if candidate in catalog:
            return catalog[candidate]
    return None


def _story_status(
    story_id: str, status_map: dict[str, tuple[str, str]], issues: list[str]
) -> str | None:
    entry = status_map.get(story_id.casefold())
    if entry is None:
        issues.append(f"missing status for story {story_id}")
        return None
    status = entry[1]
    if status not in ALLOWED_STATUSES:
        issues.append(f"unknown status for story {story_id}: {status}")
        return None
    return status


def _yaml_repository_report(
    root: Path,
    manifest: dict,
    repository: str,
    surfaces: Sequence[str],
    status_map: dict[str, tuple[str, str]],
    index_path: Path,
) -> RepositoryReport:
    index = _load_yaml(index_path)
    raw_stories = index.get("stories")
    if not isinstance(raw_stories, list):
        raise SurfaceStatusError(f"stories must be a list in {index_path.name}")

    records: list[StoryRecord] = []
    issues: list[str] = []
    seen: set[str] = set()
    default_surface = surfaces[0] if len(surfaces) == 1 else "?"
    for raw_story in raw_stories:
        if not isinstance(raw_story, dict) or not raw_story.get("id"):
            issues.append(f"invalid story entry in {index_path.name}")
            continue
        story_id = str(raw_story["id"])
        normalized = story_id.casefold()
        if normalized in seen:
            issues.append(f"duplicate story ID in story index: {story_id}")
            continue
        seen.add(normalized)
        status = _story_status(story_id, status_map, issues)
        if status is None:
            continue
        surface = str(raw_story.get("surface") or default_surface)
        if surface not in surfaces:
            issues.append(f"story {story_id} uses unregistered surface: {surface}")
        spec = raw_story.get("spec")
        validation = raw_story.get("validation")
        for field, reference in (("spec", spec), ("validation", validation)):
            if reference is None or not isinstance(reference, str):
                continue
            if "/" in reference or reference.endswith((".md", ".yaml", ".yml")):
                ref_path = _repo_relative(root, reference, f"{story_id}.{field}")
                if not ref_path.exists():
                    issues.append(f"missing {field} for story {story_id}: {reference}")
        records.append(
            StoryRecord(
                repository=repository,
                surface=surface,
                story_id=story_id,
                status=status,
                title=str(raw_story.get("title") or story_id),
                kind=str(raw_story.get("kind") or "surface"),
                spec=str(spec) if spec is not None else None,
                validation=str(validation) if validation is not None else None,
            )
        )

    indexed_ids = {str(raw["id"]).casefold() for raw in raw_stories if isinstance(raw, dict) and raw.get("id")}
    for normalized, (original, _) in status_map.items():
        if normalized not in indexed_ids:
            issues.append(f"tracker story is missing from story index: {original}")
    if issues:
        raise SurfaceStatusError(issues)
    return RepositoryReport(repository, True, tuple(records))


def _markdown_repository_report(
    root: Path,
    manifest: dict,
    repository: str,
    surfaces: Sequence[str],
    status_map: dict[str, tuple[str, str]],
    index_path: Path,
) -> RepositoryReport:
    catalog = _markdown_catalog(index_path)
    records: list[StoryRecord] = []
    issues: list[str] = []
    default_surface = surfaces[0] if surfaces else "?"
    for normalized, (story_id, _) in status_map.items():
        status = _story_status(story_id, status_map, issues)
        if status is None:
            continue
        catalog_entry = _catalog_lookup(catalog, story_id)
        if catalog_entry:
            surface, title = catalog_entry
        else:
            surface = _surface_from_story_id(story_id, surfaces)
            title = story_id.replace("-", " ")
        if surface not in surfaces:
            issues.append(f"story {story_id} uses unregistered surface: {surface}")
        records.append(
            StoryRecord(
                repository=repository,
                surface=surface,
                story_id=story_id,
                status=status,
                title=title,
                kind="surface",
                spec=None,
                validation=None,
            )
        )
    if issues:
        raise SurfaceStatusError(issues)
    return RepositoryReport(repository, True, tuple(records))


def _repository_report(root: Path) -> RepositoryReport:
    manifest_path = root / "bmad-surface.yaml"
    if not manifest_path.exists():
        raise SurfaceStatusError(f"missing registration: {manifest_path.name}")
    manifest = _load_yaml(manifest_path)
    repository = str(manifest.get("repository") or root.name)
    planning = manifest.get("planning")
    surfaces_data = manifest.get("surfaces")
    if not isinstance(surfaces_data, list):
        raise SurfaceStatusError(f"surfaces must be a list in {manifest_path.name}")
    surfaces = [str(item.get("id")) for item in surfaces_data if isinstance(item, dict) and item.get("id")]
    if planning == "not-applicable":
        return RepositoryReport(
            repository=repository,
            applicable=False,
            records=(),
            note=str(manifest.get("reason") or "No BMAD delivery scope"),
        )
    if planning != "bmad":
        raise SurfaceStatusError(f"unsupported planning value for {repository}: {planning}")
    if not surfaces:
        raise SurfaceStatusError(f"BMAD repository has no registered surfaces: {repository}")

    tracker_path = _repo_relative(root, manifest.get("status_tracker"), "status_tracker")
    index_path = _repo_relative(root, manifest.get("story_index"), "story_index")
    if not tracker_path.exists():
        raise SurfaceStatusError(f"missing status tracker for {repository}")
    if not index_path.exists():
        raise SurfaceStatusError(f"missing story index for {repository}")
    tracker = _load_yaml(tracker_path)
    raw_statuses = tracker.get("development_status")
    if not isinstance(raw_statuses, dict):
        raise SurfaceStatusError(f"development_status must be a mapping for {repository}")
    status_map = _status_key_map(raw_statuses)
    if index_path.suffix.casefold() in {".yaml", ".yml"}:
        return _yaml_repository_report(root, manifest, repository, surfaces, status_map, index_path)
    if index_path.suffix.casefold() == ".md":
        return _markdown_repository_report(root, manifest, repository, surfaces, status_map, index_path)
    raise SurfaceStatusError(f"unsupported story index format for {repository}: {index_path.suffix}")


def _cell(value: str | None) -> str:
    if value is None or value == "":
        return "—"
    return value.replace("|", "\\|").replace("\n", " ")


def render_report(repository_roots: Sequence[Path]) -> str:
    """Validate and render registered repositories without modifying inputs."""

    reports: list[RepositoryReport] = []
    issues: list[str] = []
    for raw_root in repository_roots:
        root = Path(raw_root)
        try:
            reports.append(_repository_report(root))
        except SurfaceStatusError as exc:
            issues.extend(f"{root.name}: {issue}" for issue in exc.issues)
    if issues:
        raise SurfaceStatusError(issues)

    records = [record for report in reports for record in report.records]
    seen: dict[str, str] = {}
    duplicate_issues: list[str] = []
    for record in records:
        normalized = record.story_id.casefold()
        previous = seen.get(normalized)
        if previous is not None:
            duplicate_issues.append(
                f"duplicate story ID across repositories: {record.story_id} ({previous}, {record.repository})"
            )
        else:
            seen[normalized] = record.repository
    if duplicate_issues:
        raise SurfaceStatusError(duplicate_issues)

    lines = [
        "# Federated BMAD status report",
        "",
        "> Derived output. Read local repository trackers for authority; do not edit this report as a status source.",
        "",
        f"Generated: {date.today().isoformat()}",
        "",
        "## Stories",
        "",
        "| Repository | Surface | Story | Status | Title | Spec | Validation |",
        "|---|---|---|---|---|---|---|",
    ]
    for record in records:
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    record.repository,
                    record.surface,
                    record.story_id,
                    record.status,
                    record.title,
                    record.spec,
                    record.validation,
                )
            )
            + " |"
        )

    not_applicable = [report for report in reports if not report.applicable]
    if not_applicable:
        lines.extend(("", "## Repositories without BMAD delivery scope", ""))
        for report in not_applicable:
            lines.append(f"- `{_cell(report.repository)}` — not applicable: {_cell(report.note)}")

    next_records = [record for record in records if record.status in {"ready-for-dev", "backlog"}]
    next_records.sort(
        key=lambda record: (
            0 if record.status == "ready-for-dev" else 1,
            record.repository.casefold(),
            record.story_id.casefold(),
        )
    )
    lines.extend(("", "## Next candidates", ""))
    if next_records:
        lines.extend(
            (
                "| Repository | Surface | Story | Status | Title |",
                "|---|---|---|---|---|",
            )
        )
        for record in next_records:
            lines.append(
                "| "
                + " | ".join(
                    _cell(value)
                    for value in (
                        record.repository,
                        record.surface,
                        record.story_id,
                        record.status,
                        record.title,
                    )
                )
                + " |"
            )
    else:
        lines.append("No `ready-for-dev` or `backlog` stories are registered.")

    return "\n".join(lines) + "\n"


def _parse_repo(value: str) -> Path:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--repo must use name=path")
    _, raw_path = value.split("=", 1)
    if not raw_path:
        raise argparse.ArgumentTypeError("--repo path must not be empty")
    return Path(raw_path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        action="append",
        required=True,
        type=_parse_repo,
        help="registered repository as name=path; repeat for each repository",
    )
    parser.add_argument("--output", type=Path, help="write the derived Markdown report here")
    args = parser.parse_args(argv)
    try:
        report = render_report(args.repo)
    except SurfaceStatusError as exc:
        for issue in exc.issues:
            print(f"error: {issue}", file=sys.stderr)
        return 2
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
