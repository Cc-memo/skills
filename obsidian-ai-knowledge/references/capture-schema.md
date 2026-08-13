# Capture Schema

## File placement

- Project: `00-AI知识库/项目/<项目名>.md`
- Problem: `00-AI知识库/问题/YYYY/YYYY-MM-DD - <问题>.md`
- Session: `00-AI知识库/会话/YYYY/YYYY-MM-DD - <任务>.md`
- Playbook: `00-AI知识库/经验/<经验名>.md`
- Inbox: `00-AI知识库/Inbox/YYYY-MM-DD - <草稿>.md`

Add a numeric suffix when two records would otherwise use the same filename.

## Required fields

All records use `schema_version: 2`. Add `source_ref` when a stable task, session, file, issue, note, or URL reference exists. Add `source_hash` only when a SHA-256 was actually computed from a stable source payload.

### Project

`schema_version`, `record_type`, `record_id`, `status`, `priority`, `created`, `updated`, `area`, `source`, `review_state`, `confidence`, `next_action`, `project_type`, `project_space`, `context_note`, `risk_log`, `event_log`, `freshness_note`, `retrieval_note`, `last_reviewed`, `review_due`, `tags`.

### Problem

`schema_version`, `record_type`, `record_id`, `status`, `severity`, `created`, `updated`, `project`, `area`, `root_cause`, `solution_type`, `reusable`, `occurrences`, `source_session`, `source`, `review_state`, `confidence`, `tags`.

### Session

`schema_version`, `record_type`, `record_id`, `status`, `outcome`, `created`, `updated`, `completed_at`, `project`, `area`, `ai_tool`, `workspace`, `knowledge_value`, `source`, `review_state`, `confidence`, `tags`.

### Playbook

`schema_version`, `record_type`, `record_id`, `status`, `maturity`, `created`, `updated`, `last_verified`, `times_used`, `area`, `applies_to`, `evidence`, `source`, `review_state`, `confidence`, `tags`.

### Inbox

`schema_version`, `record_type`, `record_id`, `status`, `capture_kind`, `created`, `updated`, `project`, `area`, `source`, `review_state`, `confidence`, `tags`.

## Controlled values

- `review_state`: `pending`, `reviewed`, `promoted`
- `confidence`: `low`, `medium`, `high`
- Project `status`: `planned`, `active`, `blocked`, `paused`, `completed`, `archived`
- Problem `status`: `open`, `investigating`, `solved`, `closed`
- Session `outcome`: `success`, `partial`, `failed`, `blocked`
- Playbook `maturity`: `draft`, `verified`, `stable`, `deprecated`
- `knowledge_value`: `low`, `medium`, `high`

## Minimal bodies

- Session: 目标、完成内容、关键决策、问题、验证、变更文件、可复用知识、遗留事项、关联记录。
- Problem: 现象、影响、环境、尝试、根因、方案、验证、防复发、可复用结论、后续记录、关联记录。`后续记录` 使用 `### YYYY-MM-DD — <事件>` 追加式时间线。
- Playbook: 适用场景、判断信号、步骤、验证清单、失败方式、不适用场景、证据。
- Project: 目标、状态、技术栈、决策、已完成、风险、下一步、关联记录。

## Problem lifecycle updates

- A repeated issue with the same symptom and root cause updates the existing problem card; do not create a date-stamped duplicate.
- Each substantial recurrence still creates a new session record and links it from the problem timeline.
- Increment `occurrences` and update `updated` on every confirmed recurrence.
- A `solved` transition requires `resolved_at`, a non-empty `root_cause`, `solution_type`, and concrete verification evidence.
- Append events under `## 后续记录` using `### YYYY-MM-DD — <事件>`; never rewrite older events.
- If the old conclusion is wrong or retired, preserve it and set `superseded_by` or `lifecycle_state: superseded`.
- Use `scripts/update_problem.py` in preview mode first; re-run with `--apply` only after reviewing the diff.

## Project spaces

- Formal project records remain in `00-AI知识库/项目/<项目名>.md` and remain the source of truth for status, priority, risks, decisions, and next action.
- Each project has an aggregation folder at `00-AI知识库/项目空间/<项目名>/` with dashboard, summary, problems, decisions, timeline, deliverables, a type-specific page, `资料/`, and `项目记录.base`.
- Project spaces are not a new `record_type`; exclude `项目空间/` from record validation and do not copy formal session/problem/playbook bodies into it.
- Supported `project_type` values: `software`, `research`, `configuration`, `document`, `system`, `general`.
- Use a WikiLink in `project` properties so the per-project Base can aggregate records reliably.

## Project Runtime Memory

- Before substantial work, read the project record, AI startup context, risk/assumption/dependency register, and append-only event log.
- Recheck repository and recent-session timestamps; record `external-change` when newer evidence invalidates the current summary.
- Active projects require `last_reviewed` and `review_due`; overdue reviews appear in the health report.
- Preserve superseded conclusions with replacement evidence instead of silently deleting them.
## Repository freshness

Project source fields are optional until a baseline is accepted:

- `repo` or `workspace`: controlled local source root.
- `freshness_watch`: explicit file/glob allowlist. Sensitive names, `.git`, dependency folders, and build outputs are excluded.
- `freshness_state`: `current`, `stale`, or `unknown`.
- `source_fingerprint` / `source_revision`: accepted baseline.
- `source_observed_fingerprint` / `source_observed_revision`: latest scan; scanning never replaces the baseline.
- `source_checked_at`, `source_accepted_at`, `source_latest_mtime`: audit timestamps.

Use `project_freshness.py --scan` for comparison and `--accept` only after human review.

## Summary classification and retrieval

Optional record fields:

- `summary_kind`: `status`, `change`, `delivery`, `verification`, `problem`, `decision`, `research`, `configuration`, `retrospective`, `method`, `risk`, or `handoff`.
- `retrieval_priority`: integer from 0 to 100.
- `supersedes` / `superseded_by`: links that preserve replaced conclusions instead of deleting history.

Legacy records do not need immediate backfill. `project_context.py` infers a deterministic category when `summary_kind` is absent, prioritizes unresolved problems, and applies a strict character budget.
## Evidence-first actual output

Optional session fields:

- `actual_output`: explicit boolean hint; never overrides missing evidence by itself.
- `output_type`: `code`, `configuration`, `document`, `research`, `decision`, `system`, or `other`.
- `deliverables`: concrete files, artifacts, releases, reports, or accepted decisions.
- `changed_files`: files or configuration paths actually changed.
- `validation_state`: `passed`, `partial`, `failed`, `not_run`, or `not_applicable`.
- `validation_evidence`: tests, build results, inspections, commands, screenshots, or source checks.
- `key_decisions`: concise decisions whose rationale can be reviewed.
- `next_action`: the next concrete action when work remains.

`output_report.py` classifies current results without changing formal records:

- `verified-delivery`: tangible output, passed validation, successful outcome, and reviewed status.
- `knowledge-output`: research/decision/method/retrospective record with `source_ref`, key decisions, and reviewed status.
- `needs-validation`: output exists but validation is missing, partial, or failed.
- 
eeds-review: delivery or research evidence is sufficient, but 
eview_state is still pending.
- `needs-evidence`: a success or decision is claimed without enough deliverable/source evidence.
- `incomplete`: no stable output was established.
- `superseded`: `superseded_by` or lifecycle metadata marks the record as replaced; it is excluded from current output totals.

Scores only sort records. They never override these classification gates. Legacy body sections are parsed as fallback, so immediate frontmatter backfill is not required.
## Fast retrieval contract

- Known project or continuation: scan source freshness, then use `project_context.py` with the matching focus.
- Similar error or cross-project method: use `search_knowledge.py --context --trusted-only` with symptom, technology, root-cause, and project keywords.
- Default retrieval excludes records with `superseded_by` or withdrawn/reverted/deprecated lifecycle state.
- Session trust uses the same evidence-first classification as `output_report.py`; legacy body sections remain supported.
- Retrieval remains lexical and deterministic. Do not claim embedding or semantic search unless a future implementation actually provides it.
