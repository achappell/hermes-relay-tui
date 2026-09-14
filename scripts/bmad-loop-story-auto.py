#!/usr/bin/env python3
"""Run a stories-mode bmad-loop story with an unattended plan gate.

The bmad-loop ``spec_checkpoint`` is intentionally a human pause. This wrapper
keeps that safety property while making the approved path unattended: it starts
one run, waits for the project's blocking spec-reviewer workflow, and resumes
only when the run is paused at the plan checkpoint *and* the reviewer wrote an
explicit pass verdict for this story. Missing, stale, malformed, or failed
verdicts are never treated as approval.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_SPEC = "_bmad-output/specs/spec-hermes-relay-tui"
VERDICT_NAME = "spec-review-verdict.json"
PLAN_CHECKPOINT = "plan-checkpoint"


def _display_path(path: Path) -> str:
    """Keep operator-facing paths portable across the two Macs."""
    home = Path.home()
    try:
        return "~" + str(path.resolve().relative_to(home))
    except ValueError:
        return str(path)


def _loop_binary() -> str:
    binary = shutil.which("bmad-loop")
    if binary is None:
        raise RuntimeError(
            "bmad-loop is not installed; run the repository's bmad-loop-setup "
            "workflow first"
        )
    return binary


def _json_command(binary: str, args: list[str], project: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [binary, *args],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    if completed.returncode != 0:
        raise RuntimeError(
            f"{shlex.join([binary, *args])} failed with exit code "
            f"{completed.returncode}"
        )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{shlex.join([binary, *args])} returned invalid JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise RuntimeError("bmad-loop returned a JSON value that was not an object")
    return document


def _validate(binary: str, project: Path, spec: str) -> bool:
    completed = subprocess.run(
        [binary, "validate", "--project", str(project), "--spec", spec, "--json"],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError:
        print(
            "bmad-loop validate did not return JSON; refusing to start the run",
            file=sys.stderr,
        )
        if completed.stdout:
            print(completed.stdout, file=sys.stderr, end="")
        return False
    if not document.get("ok") or completed.returncode != 0:
        print(json.dumps(document, indent=2, sort_keys=True), file=sys.stderr)
        return False
    return True


def _run_ids(binary: str, project: Path) -> set[str]:
    document = _json_command(binary, ["list", "--project", str(project), "--json"], project)
    runs = document.get("runs")
    if not isinstance(runs, list):
        raise RuntimeError("bmad-loop list JSON did not contain a runs list")
    return {
        str(item["run_id"])
        for item in runs
        if isinstance(item, dict) and isinstance(item.get("run_id"), str)
    }


def _status(binary: str, project: Path, run_id: str) -> dict[str, Any]:
    return _json_command(
        binary,
        ["status", "--project", str(project), "--json", run_id],
        project,
    )


def _story_is_present(status: dict[str, Any], story: str) -> bool:
    if status.get("paused_story_key") == story:
        return True
    tasks = status.get("tasks")
    return isinstance(tasks, list) and any(
        isinstance(task, dict) and task.get("story_key") == story for task in tasks
    )


def _new_story_run(
    binary: str,
    project: Path,
    before: set[str],
    story: str,
    timeout: float,
    poll_interval: float,
) -> tuple[str, dict[str, Any]] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        document = _json_command(
            binary,
            ["list", "--project", str(project), "--json"],
            project,
        )
        runs = document.get("runs")
        if not isinstance(runs, list):
            raise RuntimeError("bmad-loop list JSON did not contain a runs list")
        new_ids = [
            str(item["run_id"])
            for item in runs
            if isinstance(item, dict)
            and isinstance(item.get("run_id"), str)
            and item["run_id"] not in before
        ]
        matching: list[tuple[str, dict[str, Any]]] = []
        for run_id in new_ids:
            status = _status(binary, project, run_id)
            if _story_is_present(status, story):
                matching.append((run_id, status))
        if len(matching) == 1:
            return matching[0]
        if len(matching) > 1:
            raise RuntimeError(
                f"multiple new bmad-loop runs claim story {story!r}; refusing to "
                "guess which run to resume"
            )
        time.sleep(poll_interval)
    return None


def _read_verdict(
    project: Path,
    run_id: str,
    story: str,
    timeout: float,
    poll_interval: float,
) -> tuple[dict[str, Any] | None, Path]:
    verdict_path = project / ".bmad-loop" / "runs" / run_id / VERDICT_NAME
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if verdict_path.is_file():
            try:
                verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"review verdict at {_display_path(verdict_path)} is unreadable: {exc}"
                ) from exc
            if not isinstance(verdict, dict):
                raise RuntimeError("review verdict is not a JSON object")
            if verdict.get("story_key") != story:
                raise RuntimeError(
                    f"review verdict is for {verdict.get('story_key')!r}, not {story!r}"
                )
            return verdict, verdict_path
        time.sleep(poll_interval)
    return None, verdict_path


def _run_foreground(binary: str, args: list[str], project: Path) -> int:
    print(f"$ {shlex.join([binary, *args])}", file=sys.stderr)
    completed = subprocess.run([binary, *args], cwd=project, check=False)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one stories-mode bmad-loop story and auto-resume a passed plan review."
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="project root (default: repository containing this script)",
    )
    parser.add_argument(
        "--spec",
        default=DEFAULT_SPEC,
        help=f"stories-mode spec folder (default: {DEFAULT_SPEC})",
    )
    parser.add_argument("--story", default="3", help="stories.yaml id (default: 3)")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="seconds between run-state polls (default: 0.5)",
    )
    parser.add_argument(
        "--discovery-timeout",
        type=float,
        default=15.0,
        help="seconds to wait for the new run to appear (default: 15)",
    )
    parser.add_argument(
        "--verdict-timeout",
        type=float,
        default=10.0,
        help="seconds to wait for the reviewer verdict (default: 10)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="stop after a passing plan verdict; useful for wiring checks",
    )
    args = parser.parse_args(argv)

    if args.poll_interval <= 0 or args.discovery_timeout <= 0 or args.verdict_timeout <= 0:
        parser.error("poll and timeout values must be positive")

    project = args.project.expanduser().resolve()
    if not project.is_dir():
        print(f"project does not exist: {_display_path(project)}", file=sys.stderr)
        return 2

    try:
        binary = _loop_binary()
        if not _validate(binary, project, args.spec):
            print("bmad-loop preflight failed; nothing was started", file=sys.stderr)
            return 2

        before = _run_ids(binary, project)
        run_rc = _run_foreground(
            binary,
            [
                "run",
                "--project",
                str(project),
                "--spec",
                args.spec,
                "--story",
                args.story,
            ],
            project,
        )
        if run_rc != 0:
            print(f"bmad-loop run stopped with exit code {run_rc}; not resuming", file=sys.stderr)
            return run_rc

        found = _new_story_run(
            binary,
            project,
            before,
            args.story,
            args.discovery_timeout,
            args.poll_interval,
        )
        if found is None:
            print(
                f"could not identify the new bmad-loop run for story {args.story!r}; "
                "not resuming",
                file=sys.stderr,
            )
            return 3
        run_id, status = found

        if status.get("status") != "paused" or status.get("paused_stage") != PLAN_CHECKPOINT:
            print(
                f"run {run_id} did not pause at the plan checkpoint "
                f"(status={status.get('status')!r}, stage={status.get('paused_stage')!r}); "
                "not resuming",
                file=sys.stderr,
            )
            return 3

        verdict, verdict_path = _read_verdict(
            project,
            run_id,
            args.story,
            args.verdict_timeout,
            args.poll_interval,
        )
        if verdict is None:
            print(
                f"no reviewer verdict at {_display_path(verdict_path)}; "
                "the plan remains paused",
                file=sys.stderr,
            )
            return 4

        verdict_status = verdict.get("status")
        if verdict_status != "pass" or verdict.get("phase") != "plan":
            findings = verdict.get("findings", [])
            print(
                f"spec reviewer returned {verdict_status!r}; the plan remains paused",
                file=sys.stderr,
            )
            if findings:
                print(json.dumps(findings, indent=2, sort_keys=True), file=sys.stderr)
            return 4

        print(f"spec reviewer passed; resuming run {run_id}", file=sys.stderr)
        if args.no_resume:
            return 0
        return _run_foreground(
            binary,
            ["resume", "--project", str(project), run_id],
            project,
        )
    except (OSError, RuntimeError) as exc:
        print(f"bmad-loop supervisor: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
