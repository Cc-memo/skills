# 问题解决方案索引

## 设计

旧问题召回采用本地、确定性的两阶段流程：

1. 从 `problem-solution-index.json` 查询可信的已解决问题卡和稳定/已验证经验卡。
2. 按错误签名、现象、技术、别名、标签、项目和根因排序。
3. 只返回少量 `record_id` 候选，控制上下文和 token。
4. 用户或代理选中候选后，按 `record_id` 读取完整问题卡。
5. 必要时再读取相关会话作为证据，而不是把会话当作答案。

索引排除未验证、调查中、撤回和已被替代的记录。索引缺失或损坏时，程序降级到原有词法扫描，并继续把未验证记录标为线索。

## 维护

正式问题卡或经验卡发生新增、更新、晋升、替代后运行：

```powershell
python scripts/build_solution_index.py
python scripts/recall_solution.py --query "错误签名或症状" --mode cue --limit 3
python scripts/recall_solution.py --record-id "selected-record-id" --mode detail
```

不要手工把会话全文复制进索引。索引是目录，不是第二份知识正文；正文仍以 Obsidian 正式记录为准。
