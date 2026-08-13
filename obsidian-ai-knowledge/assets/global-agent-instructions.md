# AI Knowledge Capture

- For substantial work involving an existing project or repeated problem, invoke `$obsidian-ai-knowledge` before implementation.
- For repeated problems, use token-efficient two-stage recall: `recall_solution.py --mode cue --limit 3`, then `--record-id <id> --mode detail`.
- Before the final response of substantial work, use `$obsidian-ai-knowledge` to decide whether to capture verified results.
- Update an existing problem card when the symptom and root cause match; append a dated `## 后续记录` event instead of creating a duplicate.
- Never store passwords, API keys, tokens, full cookies, authorization headers, private keys, or private customer data.