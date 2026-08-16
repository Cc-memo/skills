# Retrieval Routing

Use one lightweight route before loading details.

## Problem route

For errors, symptoms, configuration failures, and repeated technical issues:

```powershell
python scripts/recall_solution.py --query "error or symptom" --mode probe
```

This route searches trusted solved problems and stable or verified playbooks.

## Decision route

For research conclusions, previous choices, comparisons, rollback reasons, and retired approaches:

```powershell
python scripts/recall_solution.py --query "why this approach was rolled back" --mode probe --route decision
```

This route searches compact summaries of trusted decision, research, retrospective, method, and rollback sessions.

Reviewed delivery sessions may opt in with `decision_index: true` when they contain a reusable choice, comparison result, or implementation rationale. Do not use this flag merely because a session has a `key_decisions` list.

Auto routing gives technical failure signals such as errors, exceptions, failed installs, and broken configuration precedence over generic decision words. This prevents queries such as “why did this configuration error occur” from bypassing the solved-problem index.

## Project route

For continuing a named project:

```powershell
python scripts/recall_solution.py --query "continue project" --mode probe --route project --project "Project Name"
```

The probe returns only project status, freshness, next action, and the instruction to build a focused project context pack.
Project freshness is checked against the current watched repository/files during the probe. If it is `stale`, do not load the old context pack as authoritative; review the change and run `project_freshness.py --scan`, then accept a new baseline only after inspection.

## Index maintenance

After changing a trusted problem, playbook, decision, research record, or rollback record:

```powershell
python scripts/build_memory_indexes.py
```

Sessions remain evidence. They are not added to the technical solution index.

If the decision index is missing, the fallback scans only records that satisfy the same trusted decision criteria; it never treats every session as a prior answer.

Both compact indexes carry a source manifest. When a knowledge record changes, the old index is treated as unavailable and the problem route falls back to deterministic lexical retrieval while reporting that the index should be rebuilt.
