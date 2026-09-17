# Story issue tracking

The local BMAD artifacts remain authoritative for story scope, validation, and
status. GitHub issues and Project #3 mirror the accepted story records.

The TUI uses `_bmad-output/planning-artifacts/epics.md` as its story map; it has
no checked-in issue URL index. Its workflow matches an issue by the exact
`Sprint Key` marker, or the full story key in the title for older issues. Pull
requests are excluded; multiple matches stop the workflow instead of guessing.

Story pull requests target their PRD branch. Completion checks use that exact
pull request and its current head revision, including required checks that do
not come from GitHub Actions. A missing pull request or missing checks is not
green. The workflow waits for a result before changing the issue to `done` or
closing it.

BMAD setup can regenerate the runtime copies under
`_bmad/_config/custom/workflows/common/`. The repository-owned sources are in
`_bmad/custom/repo-issue-tracking/workflows/common/`. After refreshing BMAD,
run `scripts/apply_repo_issue_tracking_overrides.sh`; CI checks that the runtime
copies still match with `--check`.
