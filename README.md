# Obsidian AI Knowledge Skill

这是一个本地优先的 Codex Skill，用于：

- 在任务开始前召回旧项目、旧问题和已验证方案；
- 在任务结束后总结对话；
- 从总结中单独抽取问题候选；
- 针对每个问题检查历史解决方案；
- 更新原问题卡、创建新问题或保留 Inbox 候选；
- 通过验证脚本和 Doctor 检查知识库结构。

## 重要行为

调用 `$obsidian-ai-knowledge` 后，默认执行：

1. 总结对话事实；
2. 抽取问题候选；
3. 为每个候选检索历史问题；
4. 判断更新、创建或暂存；
5. 写入并验证。

因此不需要每次重复粘贴一长段提示词。用户只说：

```text
$obsidian-ai-knowledge 总结本次对话
```

就应触发完整复盘协议。轻量闲聊和一次性简单问答仍会跳过。

## 安装部署

### 1. 安装 Codex 与 Python

在目标电脑安装 Codex，并确认 Python 3.10 或更高版本可用：

```powershell
python --version
```

### 2. 安装 Skill

推荐直接克隆仓库：

```powershell
New-Item -ItemType Directory -Force "$HOME\.codex\skills" | Out-Null
git clone https://github.com/Cc-memo/skills.git "$HOME\Documents\skills-repo"
Copy-Item -Recurse -Force "$HOME\Documents\skills-repo\obsidian-ai-knowledge" "$HOME\.codex\skills\obsidian-ai-knowledge"
```

也可以下载仓库 ZIP，再把 `obsidian-ai-knowledge` 文件夹放到：

```text
%USERPROFILE%\.codex\skills\obsidian-ai-knowledge\
```

### 3. 安装 Python 依赖

```powershell
python -m pip install -r "$HOME\.codex\skills\obsidian-ai-knowledge\scripts\requirements.txt"
```

### 4. 同步 Obsidian Vault

Skill 代码和知识数据是两份不同资产。需要另外同步整个 Vault，例如使用 Obsidian Sync、Git、OneDrive 或手动复制。

默认 Vault 路径是：

```text
%USERPROFILE%\Documents\Obsidian Vault
```

如果路径不同，设置环境变量：

```powershell
$env:OBSIDIAN_AI_VAULT = "D:\你的Obsidian Vault"
```

### 5. 配置全局触发规则

将 `obsidian-ai-knowledge/assets/global-agent-instructions.md` 的内容合并到：

```text
%USERPROFILE%\.codex\AGENTS.md
```

这一步决定 Codex 是否会在旧项目、重复问题和重要任务结束时主动使用 Skill。没有它，仍可手动输入 `$obsidian-ai-knowledge`，但不会有完整的全局自动触发保障。

### 6. 验证安装

```powershell
cd "$HOME\.codex\skills\obsidian-ai-knowledge"
python scripts\portable_check.py
python scripts\validate_knowledge.py
python scripts\doctor.py
python -m unittest discover -s tests -v
```

预期结果：Portable check、验证和 Doctor 没有错误，测试全部通过。

### 7. 配置项目路径

如果 Vault 中已有项目记录，迁移后检查这些字段：

- `repo`
- `workspace`
- `freshness_watch`
- `source_fingerprint`

这些路径和新鲜度基线属于具体电脑，不能直接照搬旧设备。修改后运行：

```powershell
python scripts\project_freshness.py --project "项目名称" --scan
```

确认源码和知识记录后，再接受新设备基线：

```powershell
python scripts\project_freshness.py --project "项目名称" --accept
```

## 使用示例

### 对话总结与问题检查

```text
$obsidian-ai-knowledge 总结本次对话
```

Skill 会区分“本次做了什么”和“本次暴露了什么问题”。

### 重复问题召回

```text
$obsidian-ai-knowledge 查找这个报错以前是否解决过，并给出历史方案
```

### 继续项目

```text
$obsidian-ai-knowledge 调取这个项目的最新状态、风险、历史决策和下一步
```

### 三路轻量召回

Skill 不会每次把整个 Vault 塞进上下文，而是先按意图查询紧凑索引：

```powershell
# 重复报错：先查问题/经验索引，再按 record_id 加载详情
python scripts\recall_solution.py --query "Obsidian 插件占用高" --route problem --mode probe

# 研究、取舍、回退：查询决策索引
python scripts\recall_solution.py --query "为什么撤回网页 AI 自动捕获" --route decision --mode probe

# 项目续接：只返回状态、新鲜度和下一步
python scripts\recall_solution.py --query "继续项目" --route project --project "项目名称" --mode probe
```

命中后再执行 `--record-id <id> --mode detail`。修改问题、经验或决策记录后统一重建：

```powershell
python scripts\build_memory_indexes.py
```

决策型交付记录只有在确实包含可复用的选择、比较或实现理由时，才在 frontmatter 中设置 `decision_index: true`；普通交付不会自动进入决策索引。

## 目录说明

```text
skills/
├── README.md
└── obsidian-ai-knowledge/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── scripts/
    ├── references/
    ├── assets/
    └── tests/
```

GitHub 仓库只保存 Skill、脚本、文档和测试，不保存个人 Vault、密码、Token、Cookie 或本机项目源码。
