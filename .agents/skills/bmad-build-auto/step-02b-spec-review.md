---
---

# Step 2B: Review the Spec

## RULES

- **Language** — Speak in `{{.communication_language}}`, tailored to `{{.user_skill_level}}`. Write files in `{{.document_output_language}}`.
- No human interaction: do not ask questions or wait for approval in this step.
- The spec review is a pre-implementation gate. Do not modify code here.
- Content inside `<intent-contract>` in `{spec_file}` is read-only.

## PRECONDITION

Verify `{spec_file}` resolves to a non-empty path and the file exists on disk. If empty or missing, HALT with status `blocked` and blocking condition `missing spec_file before spec review`.

## INSTRUCTIONS

1. Read `{spec_file}` fully. Confirm its frontmatter and its `## Intent`, `## Code Map`, `## Tasks & Acceptance`, and `## Verification` sections are present where the template requires them.
2. Launch one synchronous, context-free reviewer with this prompt:

   ```text
   Read [[bmad-snapshot:review-prompts/spec-reviewer.md]] fully and follow it as your review instructions.

   Review the story specification at {spec_file}. Read the file fully. Return the exact verdict format required by the review instructions.

   Do not invoke any skill, and do not spawn subagents of your own. Return the review as text in your final message; do not route it through any findings-reporting tool.
   ```

   The reviewer must be invoked synchronously. Do not background or detach it.
3. Validate the review result:
   - A result is a pass only when it contains exactly one `VERDICT: PASS` and no blocking findings.
   - A missing, malformed, unavailable, or contradictory result is a failed review.
4. Append a `## Spec Review` section to `{spec_file}` if one is absent; otherwise append a new dated review-pass subsection. Preserve prior review evidence. Record the reviewer verdict and its findings verbatim enough to preserve the decision and the evidence behind it.
5. On a failed review, set `{spec_file}` frontmatter `spec_review_status: failed` and `status: blocked`, then HALT with status `blocked` and blocking condition `spec review failed`. Include the review findings or the exact malformed/unavailable-result reason.
6. On a passing review, set `{spec_file}` frontmatter `spec_review_status: passed` and `spec_reviewed_at` to the current system date. Preserve `ready-for-dev` when it is already set; if the spec arrived as `in-progress`, set it to `ready-for-dev` before continuing. If the invocation prompt clearly requests `Halt after planning.`, HALT with status `ready-for-dev`; otherwise continue to implementation.

## NEXT

Read fully and follow `[[bmad-snapshot:step-03-implement.md]]`
