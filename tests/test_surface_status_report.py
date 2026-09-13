from pathlib import Path

import pytest
import yaml

from scripts.render_surface_status import SurfaceStatusError, main, render_report


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
        manifest["status_tracker"] = (
            "_bmad-output/implementation-artifacts/sprint-status.yaml"
        )
        manifest["story_index"] = (
            "_bmad-output/implementation-artifacts/story-index.yaml"
        )
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
def test_invalid_local_records_fail_validation(
    tmp_path: Path, change: str, message: str
):
    repo = write_repository(
        tmp_path / "ios",
        stories=[{"id": "1-I-1", "title": "Story", "kind": "surface"}],
        statuses={"1-i-1": "done"},
    )
    if change == "missing_tracker":
        (repo / "_bmad-output/implementation-artifacts/sprint-status.yaml").unlink()
    elif change == "unknown_status":
        tracker = yaml.safe_load(
            (
                repo / "_bmad-output/implementation-artifacts/sprint-status.yaml"
            ).read_text()
        )
        tracker["development_status"]["1-i-1"] = "paused"
        (repo / "_bmad-output/implementation-artifacts/sprint-status.yaml").write_text(
            yaml.safe_dump(tracker)
        )
    elif change == "missing_status":
        tracker = yaml.safe_load(
            (
                repo / "_bmad-output/implementation-artifacts/sprint-status.yaml"
            ).read_text()
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


def test_markdown_catalog_prefers_epic_specific_story_title(tmp_path: Path):
    repo = tmp_path / "tui"
    repo.mkdir()
    (repo / "bmad-surface.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "repository": "hermes-relay-tui",
                "planning": "bmad",
                "surfaces": [{"id": "P", "name": "ReSpeaker Puck"}],
                "status_tracker": "sprint-status.yaml",
                "story_index": "epics.md",
            }
        ),
        encoding="utf-8",
    )
    (repo / "sprint-status.yaml").write_text(
        yaml.safe_dump(
            {
                "development_status": {
                    "2-p-1-expose-room-state": "backlog",
                }
            }
        ),
        encoding="utf-8",
    )
    (repo / "epics.md").write_text(
        "| `P-1` | ReSpeaker Puck | Generic Puck title. |\n"
        "| `2-P-1` | ReSpeaker Puck | Epic-specific Puck title. |\n",
        encoding="utf-8",
    )

    report = render_report([repo])

    assert "Epic-specific Puck title." in report
    assert "Generic Puck title." not in report


def test_markdown_catalog_mismatch_fails_validation(tmp_path: Path):
    repo = tmp_path / "tui"
    repo.mkdir()
    (repo / "bmad-surface.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "repository": "hermes-relay-tui",
                "planning": "bmad",
                "surfaces": [{"id": "P", "name": "ReSpeaker Puck"}],
                "status_tracker": "sprint-status.yaml",
                "story_index": "epics.md",
            }
        ),
        encoding="utf-8",
    )
    (repo / "sprint-status.yaml").write_text(
        yaml.safe_dump({"development_status": {"2-p-9-missing": "backlog"}}),
        encoding="utf-8",
    )
    (repo / "epics.md").write_text(
        "| `2-P-1` | ReSpeaker Puck | Existing story. |\n",
        encoding="utf-8",
    )

    with pytest.raises(SurfaceStatusError, match="missing from story index"):
        render_report([repo])


def test_declared_legacy_story_alias_resolves_markdown_catalog(tmp_path: Path):
    repo = tmp_path / "tui"
    repo.mkdir()
    (repo / "bmad-surface.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "repository": "hermes-relay-tui",
                "planning": "bmad",
                "surfaces": [{"id": "T", "name": "Textual TUI"}],
                "status_tracker": "sprint-status.yaml",
                "story_index": "epics.md",
                "story_aliases": {"1-1-legacy": "T-1"},
            }
        ),
        encoding="utf-8",
    )
    (repo / "sprint-status.yaml").write_text(
        yaml.safe_dump({"development_status": {"1-1-legacy": "done"}}),
        encoding="utf-8",
    )
    (repo / "epics.md").write_text(
        "| `T-1` | TUI | Authorized initiation. |\n",
        encoding="utf-8",
    )

    report = render_report([repo])

    assert "Authorized initiation." in report


@pytest.mark.parametrize(
    ("reference", "message"),
    [("../outside.md", "stay inside"), ("missing-artifact", "missing spec")],
)
def test_artifact_references_are_relative_and_exist(
    tmp_path: Path, reference: str, message: str
):
    repo = write_repository(
        tmp_path / "ios",
        stories=[
            {"id": "1-I-1", "title": "Story", "kind": "surface", "spec": reference}
        ],
        statuses={"1-i-1": "done"},
    )

    with pytest.raises(SurfaceStatusError, match=message):
        render_report([repo])


def test_cli_requires_the_complete_hermes_roster(tmp_path: Path, capsys):
    repo = write_repository(
        tmp_path / "ios",
        stories=[{"id": "1-I-1", "title": "Story", "kind": "surface"}],
        statuses={"1-i-1": "done"},
    )

    result = main(["--repo", f"ios={repo}"])

    assert result == 2
    assert "missing required repository aliases" in capsys.readouterr().err


def test_cli_preserves_repository_aliases_for_worktree_roster(tmp_path: Path):
    entries = []
    for number, alias in enumerate(("tui", "ios", "android", "home"), start=1):
        repo = write_repository(
            tmp_path / alias,
            repository=f"hermes-relay-{alias}",
            stories=[{"id": f"1-I-{number}", "title": alias, "kind": "surface"}],
            statuses={f"1-i-{number}": "done"},
        )
        entries.extend(("--repo", f"{alias}={repo}"))
    write_repository(
        tmp_path / "agent", repository="hermes-agent", planning="not-applicable"
    )
    entries.extend(("--repo", f"agent={tmp_path / 'agent'}"))
    output = tmp_path / "surface-status-report.md"

    result = main([*entries, "--output", str(output)])

    assert result == 0
    report = output.read_text(encoding="utf-8")
    assert "hermes-relay-ios" in report
    assert "hermes-agent" in report


def test_cli_reads_relative_repository_roster(tmp_path: Path):
    repository_root = tmp_path / "repositories"
    repository_root.mkdir()
    roster = []
    for number, alias in enumerate(("tui", "ios", "android", "home"), start=1):
        write_repository(
            repository_root / alias,
            repository=f"hermes-relay-{alias}",
            stories=[{"id": f"1-I-{number}", "title": alias, "kind": "surface"}],
            statuses={f"1-i-{number}": "done"},
        )
        roster.append({"name": alias, "path": f"repositories/{alias}"})
    write_repository(
        repository_root / "agent", repository="hermes-agent", planning="not-applicable"
    )
    roster.append({"name": "agent", "path": "repositories/agent"})
    config = tmp_path / "surface-repositories.yaml"
    config.write_text(yaml.safe_dump({"repositories": roster}), encoding="utf-8")
    output = tmp_path / "surface-status-report.md"

    result = main(["--config", str(config), "--output", str(output)])

    assert result == 0
    assert "hermes-relay-home" in output.read_text(encoding="utf-8")


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
