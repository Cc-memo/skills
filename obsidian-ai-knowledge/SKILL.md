---
name: obsidian-ai-knowledge
description: Use for substantial work, repeated problems, project continuation, verified summaries, and explicit knowledge capture. Probe old solutions cheaply before loading details; persist only verified facts.
---

# Obsidian AI Knowledge

Local-first, evidence-first memory for Codex. Do not archive full conversations.

## When to use

Use for multi-step coding, debugging, research, configuration, project continuation, repeated errors, or explicit summary/capture requests. Skip casual chat and trivial answers.

## Low-cost recall

For a suspected repeated problem, run the cheap probe first:

```powershell
python scripts/recall_solution.py --query "symptom or error" --mode probe
```

If `match` is false, solve directly. If `match` is true, load only the selected record:

```powershell
python scripts/recall_solution.py --record-id "record-id" --mode detail
```

Use `--mode cue` only when comparing several candidates and `--mode full` only for audits. The primary index contains trusted solved problems and stable/verified playbooks. Sessions are supporting evidence, not primary answers.

Rebuild after changing a problem/playbook:

```powershell
python scripts/build_solution_index.py
```

The index is deterministic lexical retrieval, not embeddings. Exact error signatures rank highest. Missing or invalid indexes fall back to lexical search.

## Capture

Capture a concise session after substantial work. Extract problem candidates separately from the summary. Update a matching problem with a dated event; create a problem only after root cause and verification are established. Keep uncertain material in Inbox. Never mark unverified work solved.

Required safeguards:

- Preserve superseded history with `superseded_by` or lifecycle metadata.
- Never store passwords, tokens, cookies, private keys, authorization headers, or private customer data.
- Use `schema_version: 2`, stable lowercase `record_id`, and `source_ref` when available.
- Validate after capture with `python scripts/validate_knowledge.py`.
- Run `python scripts/doctor.py` after schema, script, settings, or installation changes.

## References

- Full operating protocol: `references/full-protocol.md`
- Capture schema: `references/capture-schema.md`
- Problem lifecycle: `references/problem-lifecycle.md`
- Solution index: `references/solution-index.md`
- Conversation review: `references/conversation-review.md`
- Portability: `references/portability.md`
