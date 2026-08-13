# 跨设备使用

Skill、知识库数据和全局触发规则是三份独立资产：

1. Skill：复制到目标设备的 `$CODEX_HOME/skills/obsidian-ai-knowledge/`，通常是 `~/.codex/skills/obsidian-ai-knowledge/`。
2. Vault：使用 Obsidian Sync、Git、OneDrive 或其他方式同步；也可以设置 `OBSIDIAN_AI_VAULT` 指向目标设备的实际 Vault。
3. 全局触发规则：在目标设备的 `~/.codex/AGENTS.md` 中加入按需召回和任务结束沉淀规则。

项目记录中的 `repo`、`workspace` 和 `freshness_watch` 可能包含设备本地路径。迁移后应更新项目档案并重新执行 `project_freshness.py --scan`；不要沿用另一台设备的 accepted fingerprint。

## 最小迁移步骤

1. 同步 Obsidian Vault。
2. 复制或解压 Skill 到 `$CODEX_HOME/skills/obsidian-ai-knowledge/`。
3. 安装 `PyYAML`：`python -m pip install -r scripts/requirements.txt`。
4. 如 Vault 不在默认目录，设置 `OBSIDIAN_AI_VAULT`。
5. 将 `assets/global-agent-instructions.md` 的规则合并到目标设备全局说明。
6. 运行 `python scripts/portable_check.py`。
7. 运行 `python scripts/validate_knowledge.py`，再运行 `python scripts/doctor.py`。

## 不会自动同步的内容

- `~/.codex/skills/` 中的 Skill 文件；
- `~/.codex/AGENTS.md` 和其他客户端全局规则；
- 未同步的 Obsidian Vault；
- 每台设备不同的项目源码路径和仓库新鲜度基线。