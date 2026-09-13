from pathlib import Path

import pytest
import yaml

from scripts.render_surface_status import SurfaceStatusError, render_report


def write_repository(
    root: Path,
    *,
    repository: str = "hermes-relay-ios",
    planning: str = "bmad",
    stories: list[dict] | None = None,
    statuses: dict[str, str] | None = None,
) -> Path:
    root.mkdir()
    manifest = {
        "schema_version": 1,
        "repository": repository,
        "planning": planning,
        "surfaces": [{"id": "I", "name": "iOS Client"}],
    }
    if planning == "bmad":
        manifest["status_tracker"] = "_bmad-output/implementation-artifacts/sprint-status.yaml"
        manifest["story_index"] = "_bmad-output/implementation-artifacts/story-index.yaml"
    (root / "bmad-surface.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    if planning == "bmad":
        artifact_root = root / "_bmad-output/implementation-artifacts"
        artifact_root.mkdir(parents=True)
        (artifact_root / "story-index.yaml").write_text(
            yaml.safe_dump({"schema_version": 1, "stories": stories or []}),
            encoding="utf-8",
        )
        (artifact_root / "sprint-status.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "project": repository,
                    "status_authority": "local",
                    "development_status": statuses or {},
                }
            ),
            encoding="utf-8",
        )
    return root


def test_report_reads_local_status_and_orders_next_candidates(tmp_path: Path):
    first = write_repository(
        tmp_path / "ios",
        stories=[
            {"id": "1-I-1", "title": "Finished", "kind": "surface"},
            {"id": "1-I-2", "title": "Ready item", "kind": "surface"},
            {"id": "1-I-3", "title": "Backlog item", "kind": "surface"},
        ],
        statuses={"1-i-1": "done", "1-i-2": "ready-for-dev", "1-i-3": "backlog"},
    )
    second = write_repository(
        tmp_path / "agent",
        repository="hermes-agent",
        planning="not-applicable",
    )

    report = render_report([first, second])

    assert "derived output" in report.lower()
    assert "hermes-relay-ios" in report
    assert "Ready item" in report
    assert "hermes-agent" in report
    assert report.index("Ready item") < report.index("Backlog item")
    assert "Next candidates" in report


def test_not_applicable_repository_contributes_no_story_rows(tmp_path: Path):
    repo = write_repository(
        tmp_path / "agent",
        repository="hermes-agent",
        planning="not-applicable",
    )

    report = render_report([repo])

    assert "hermes-agent" in report
    assert "not applicable" in report.lower()
    assert "Next candidates" in report


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("missing_tracker", "status tracker"),
        ("unknown_status", "unknown status"),
        ("missing_status", "missing status"),
    ],
)
def test_invalid_local_records_fail_validation(tmp_path: Path, change: str, message: str):
    repo = write_repository(
        tmp_path / "ios",
        stories=[{"id": "1-I-1", "title": "Story", "kind": "surface"}],
        statuses={"1-i-1": "done"},
    )
    if change == "missing_tracker":
        (repo / "_bmad-output/implementation-artifacts/sprint-status.yaml").unlink()
    elif change == "unknown_status":
        tracker = yaml.safe_load(
            (repo / "_bmad-output/implementation-artifacts/sprint-status.yaml").read_text()
        )
        tracker["development_status"]["1-i-1"] = "paused"
        (repo / "_bmad-output/implementation-artifacts/sprint-status.yaml").write_text(
            yaml.safe_dump(tracker)
        )
    elif change == "missing_status":
        tracker = yaml.safe_load(
            (repo / "_bmad-output/implementation-artifacts/sprint-status.yaml").read_text()
        )
        tracker["development_status"].clear()
        (repo / "_bmad-output/implementation-artifacts/sprint-status.yaml").write_text(
            yaml.safe_dump(tracker)
        )

    with pytest.raises(SurfaceStatusError, match=message):
        render_report([repo])


def test_duplicate_story_ids_fail_validation(tmp_path: Path):
    stories = [{"id": "1-I-1", "title": "Story", "kind": "surface"}]
    first = write_repository(
        tmp_path / "first", stories=stories, statuses={"1-i-1": "done"}
    )
    second = write_repository(
        tmp_path / "second",
        repository="other-repo",
        stories=stories,
        statuses={"1-i-1": "backlog"},
    )

    with pytest.raises(SurfaceStatusError, match="duplicate story ID"):
        render_report([first, second])


def test_renderer_does_not_modify_input_repositories(tmp_path: Path):
    repo = write_repository(
        tmp_path / "ios",
        stories=[{"id": "1-I-1", "title": "Story", "kind": "surface"}],
        statuses={"1-i-1": "done"},
    )
    before = sorted(
        (path.relative_to(repo), path.read_bytes())
        for path in repo.rglob("*")
        if path.is_file()
    )

    render_report([repo])

    after = sorted(
        (path.relative_to(repo), path.read_bytes())
        for path in repo.rglob("*")
        if path.is_file()
    )
    assert after == before
