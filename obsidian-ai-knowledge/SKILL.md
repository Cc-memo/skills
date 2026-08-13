---
name: obsidian-ai-knowledge
description: Retrieve and persist verified project memory in the user's Obsidian knowledge system. Use before substantial work when continuing an existing project, revisiting a prior decision, or encountering a repeated error; use token-efficient candidate-to-detail recall for old solutions. Use after substantial coding, debugging, configuration, research, document, or system tasks to summarize the conversation, expose problem candidates, recall prior solutions, and create or update sessions, projects, problem cards, playbooks, and Inbox drafts. Update matching unresolved problems with dated follow-up events instead of creating duplicates. Skip casual chat and trivial one-step answers.
---

# Obsidian AI Knowledge

Capture durable facts from completed work without turning the vault into a transcript archive. A conversation summary and a problem record are different outputs: the summary records what happened; the problem review exposes symptoms, evidence, unresolved questions, and prior-solution matches.

## Dependencies

- Use `$obsidian-markdown` whenever creating or editing Obsidian Markdown.
- Use `$obsidian-bases` whenever creating or editing `.base` files.
- Python scripts require `PyYAML`; see `scripts/requirements.txt`.

## Locations and Configuration

- Default vault: `%USERPROFILE%\Documents\Obsidian Vault`
- Override vault: set `OBSIDIAN_AI_VAULT` or pass `--vault`.
- System configuration: `00-AI知识库\_系统\config.yaml`
- Dashboard: `00-AI知识库\00 - AI知识库首页.md`
- Health report: `00-AI知识库\_系统\知识库健康报告.md`
- Capture policy: `00-AI知识库\_系统\沉淀规则.md`
- Sensitive-data policy: `00-AI知识库\_系统\敏感信息规则.md`

Read `references/capture-schema.md` when creating, merging, or promoting records.
Read `references/problem-lifecycle.md` when a prior unresolved problem recurs or a solution changes. Read `references/portability.md` only when moving the Skill or Vault to another device.

## Trigger Decision

Capture when any of these are true:

- Files, configuration, documentation, or system state changed.
- The task required multi-step research, implementation, debugging, or verification.
- A root cause, durable decision, or reusable method was established.
- The user explicitly asks to summarize, record, persist, or archive the work.

Skip casual conversation, translation, trivial factual answers, and unsuccessful exploration without a stable conclusion. If the user says not to record, skip completely.

## Capture Levels

1. **Session** — factual record of substantial completed work. This is the default formal record.
2. **Problem** — create only when symptoms, investigation, root cause, solution, and verification are known.
3. **Playbook** — create or update only when a method is reusable across tasks and supported by evidence.
4. **Project** — update only current status, decisions, completed milestones, risks, and next action.
5. **Inbox** — use when confidence is low, validation is incomplete, or deduplication is uncertain.

Do not promote a guess directly into `问题` or `经验`.

## Workflow

1. Extract only task facts: objective, actions, decisions, result, validation, changed files, deliverables, and remaining work. When known, populate the optional evidence fields documented in `references/capture-schema.md`; do not guess them.
2. Search for duplicates before writing:

   `python scripts/search_knowledge.py --query "<project, problem, or method keywords>" --snippets`

3. Choose the minimum necessary writes:
   - Usually one session plus a small project update.
   - Add a problem only for a real investigated obstacle.
   - Add a playbook only after reusable knowledge is verified.
   - If a matching problem already exists, create the new session and update that problem with `scripts/update_problem.py`; append a dated `## 后续记录` event instead of creating a duplicate.
   - When the user asks to summarize a conversation, run `python scripts/conversation_review.py --input <review.json>` or follow `references/conversation-review.md`: summarize first, then extract problem candidates, recall history for each candidate, and decide update/new/Inbox.
4. Add `schema_version: 2` and a stable lowercase `record_id`.
5. Add `source_ref` whenever a task ID, session, input note, source file, issue, or URL is available. Add `source_hash` only for a stable source payload whose SHA-256 was actually computed.
6. Use `apply_patch` for vault modifications. Preserve hand-written content and update existing records instead of replacing them wholesale.
7. Link related records using Obsidian wikilinks.
8. Run validation after every capture:

   `python scripts/validate_knowledge.py`

9. Refresh the advisory health and actual-output reports after a meaningful capture:

   `python scripts/health_report.py --save`

   `python scripts/output_report.py --save`

10. When changing schema, Bases, scripts, global instructions, or installation state, also run:

   `python scripts/doctor.py`

11. Mention captured record paths briefly in the final response. Do not claim capture succeeded if validation failed.

## Promotion Rules

- `review_state: pending` and `confidence: low` belong in Inbox.
- A solved problem requires a concrete verification result.
- A verified playbook requires at least one evidence link.
- Use `maturity: stable` only after at least two independent successful uses.
- On repeated use, update `times_used` and `last_verified` instead of creating another playbook.
- On repeated occurrence, update `occurrences` and add evidence to the existing problem.

## Retrieval Rules

- At the start of substantial work, retrieve before editing when the prompt names an existing project, resembles a prior error, asks to continue earlier work, or asks why a previous decision was made.
- For a known project, run `project_freshness.py --scan` first, then build a focus-specific `project_context.py` pack. Treat `stale` as a warning that old conclusions need rechecking.
- For cross-project errors, methods, decisions, configuration, or research, run `search_knowledge.py --query "<symptoms, technology, project, or decision words>" --context --trusted-only` before broad exploration.
- For a repeated problem, use two-stage retrieval: first run `python scripts/recall_solution.py --query "<error or symptom>" --mode cue --limit 3`; then fetch only the selected answer with `--record-id <id> --mode detail`. Use `--mode full` only for audits.
- For conversation review, do not treat the whole conversation title or summary as the problem. Extract each concrete symptom, error signature, technology, project, current status, root-cause confidence, and evidence into a separate problem candidate, then recall history for that candidate.
- Use `scripts/conversation_review.py` to make this split deterministic. A historical problem match recommends updating the existing card; an unmatched or unverified candidate remains a candidate or Inbox draft until evidence is sufficient.
- Use `_系统/问题召回线索.md` as an ambient cue list when the agent may not know the exact prior wording. Regenerate it with `python scripts/build_recall_cues.py` after promoting or superseding a problem/playbook.
- After changing retrieval scoring, aliases, trust rules, or supersession behavior, run `python scripts/evaluate_retrieval.py --limit 3 --save`; all deterministic cases must pass before describing retrieval as improved.
- Search titles, IDs, tags, project, area, root cause, applicable scope, summary kind, deliverables, changed files, validation evidence, key decisions, and source references before reading full bodies.
- Evidence-first search ranks reviewed and verified results above pending or unverified records and excludes `superseded_by` / withdrawn history by default. Use `--include-superseded` only when auditing history.
- For maintenance, review, or system-audit tasks, read `_系统/知识库健康报告.md` and `_系统/实际产出报告.md` before opening many records.
- Prefer an existing record with matching root cause, decision, or verified method over a new date-stamped note, but revalidate environment-sensitive facts.
- If keyword search is insufficient, report that limitation instead of pretending semantic retrieval occurred. The current system is evidence-ranked lexical retrieval, not embeddings.
- Do not install or require an Obsidian REST API/MCP server unless filesystem access is unavailable or the user explicitly wants remote access.

## Maintenance Health

- `health_report.py` reports Inbox backlog, stale open problems, active projects without next actions, aging draft playbooks, low-confidence formal records, stubs, source coverage, and recent-session gaps.
- The health report is advisory. `validate_knowledge.py` remains authoritative for schema, provenance, links, safety, and strict pass/fail checks.
- Run `python scripts/health_report.py --save` after capture and during periodic review. Use `--strict` only in maintenance automation where any action item should fail the run.
- Change thresholds in `_系统/config.yaml` under `quality`; do not hard-code personal review intervals into notes.

## Evidence-First Output Review

- Treat code, configuration, documents, research, and decisions as different output types.
- Never infer delivery value from note length, link count, tag count, or agent activity counts.
- A verified delivery requires concrete output plus passed validation. If validation contains both successful checks and untested scope, classify it as partial.
- A research or decision output requires a stable `source_ref`, reviewable key decisions, and `review_state: reviewed` or `promoted`.
- Mark withdrawn or replaced conclusions with `superseded_by`; keep the history but exclude it from current output totals.
- Run `python scripts/output_report.py --save` to refresh `_系统/实际产出报告.md`. The report is deterministic advisory analysis and must not be described as a model-generated conclusion.
## Sensitive Data

Never store passwords, private keys, recovery phrases, API keys, access or refresh tokens, full cookies, authorization headers, session identifiers, or private customer data. Replace necessary references with placeholders such as `${TOKEN}` or `<redacted>`.

## Writing Style

- Write in concise Chinese unless the existing record uses another language.
- Separate verified facts from inference.
- Prefer root cause, decision rationale, verification, provenance, and reuse conditions over chronological narration.
- Include commands only when reusable and free of secrets.
- Do not copy the full conversation.

## Project Space Workflow

- A project record remains the formal source of truth in `项目/`; the corresponding `项目空间/<项目名>/` is an aggregation and retrospective workspace.
- New projects should be created with the QuickAdd macro `创建完整项目（推荐）` or `scripts/project_space.py`.
- Supported project types are `software`, `research`, `configuration`, `document`, `system`, and `general`.
- Do not duplicate formal session, problem, playbook, or Inbox bodies in project folders. Link them with a consistent `project` WikiLink and aggregate them through `项目记录.base`.
- Update the stage summary, decision log, deliverables, and type-specific page when a milestone materially changes the project.
- If a suspected issue lacks a verified root cause, put it in the project temporary investigation section or Inbox instead of creating a solved problem record.

## Project Runtime Memory

- Before substantial work, read the project record, AI startup context, risk/assumption/dependency register, and append-only event log.
- Recheck repository and recent-session timestamps; record `external-change` when newer evidence invalidates the current summary.
- Active projects require `last_reviewed` and `review_due`; overdue reviews appear in the health report.
- Preserve superseded conclusions with replacement evidence instead of silently deleting them.
## Repository Freshness and AI Context Packs

- Before continuing an active project, run `python scripts/project_freshness.py --project "<project>" --scan`.
- A scan records the observed fingerprint but never accepts it. After reviewing repository changes and updating knowledge, run `--accept`.
- Treat `freshness_state: stale` as a blocking warning for important implementation or handoff decisions.
- Build focused context with `python scripts/project_context.py --project "<project>" --focus handoff`.
- Supported focus profiles are `overview`, `status`, `implementation`, `debugging`, `decision`, `handoff`, and `all`.
- Context packs read only the formal vault records and controlled project-space summaries; they never ingest the entire repository or sensitive files.
- Use `_系统/调取路由.yaml` and the project's `11 - 总结分类与调取.md` to map user intent to summary categories.
