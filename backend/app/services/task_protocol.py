"""Task Protocol — 结构化任务模板，用于提升 Bots Team 中 Bot 的执行质量。

把 Coordinator 的模糊指令包装成带验收标准的结构化任务，
让 Bot 收到明确的"做到什么程度才算完成"的要求。
"""
from __future__ import annotations

import re

# ── 深度要求描述映射 ──

DEPTH_DESCRIPTIONS: dict[str, str] = {
    "shallow": "给出要点即可，不需要展开分析",
    "moderate": "适当展开分析，给出关键依据",
    "thorough": "深入分析，包含具体示例、对比和权衡取舍",
    "exhaustive": "全面详尽分析，覆盖所有边界情况、替代方案和长期影响",
}


def format_task_assignment(task: dict, content: str) -> str:
    """把普通消息包装成结构化任务模板。

    Args:
        task: 任务字典，包含 id, title, assigned_to, depth, acceptance_criteria 等
        content: Coordinator 的原始消息内容

    Returns:
        包装后的结构化任务消息
    """
    task_id = task["id"]
    title = task.get("title", "未命名任务")
    assigned_to = task.get("assigned_to", "")
    depth = task.get("depth", "thorough")
    criteria = task.get("acceptance_criteria", [])
    depth_desc = DEPTH_DESCRIPTIONS.get(depth, DEPTH_DESCRIPTIONS["thorough"])

    # 验收标准列表
    criteria_lines = ""
    if criteria:
        if isinstance(criteria, str):
            import json
            try:
                criteria = json.loads(criteria)
            except (json.JSONDecodeError, TypeError):
                criteria = [criteria]
        criteria_lines = "\n".join(f"{i+1}. {c}" for i, c in enumerate(criteria))
    else:
        criteria_lines = "1. 完整回答任务描述中提出的所有问题"

    assign_line = f"**分配给:** @{assigned_to} | " if assigned_to else ""

    return f"""---TASK---
## 任务: {title}
{assign_line}**深度要求:** {depth} | **ID:** {task_id}

### 任务描述
{content}

### 验收标准（必须全部满足）
{criteria_lines}

### 输出要求
- 深度: {depth} — {depth_desc}
- 结构清晰，使用标题和分节组织内容
- 给出具体的数据、示例或证据，而非泛泛而谈
- 完成后在回复末尾写: `TASK-COMPLETE: {task_id}`
---END-TASK---"""


def format_revision_request(task: dict, feedback: str) -> str:
    """质量不达标时，生成修改请求消息。

    Args:
        task: 任务字典
        feedback: 质量评估的反馈信息

    Returns:
        修改请求消息
    """
    task_id = task["id"]
    title = task.get("title", "")
    revision_count = task.get("revision_count", 0) + 1
    max_revisions = task.get("max_revisions", 2)
    score = task.get("quality_score")
    criteria = task.get("acceptance_criteria", [])

    if isinstance(criteria, str):
        import json
        try:
            criteria = json.loads(criteria)
        except (json.JSONDecodeError, TypeError):
            criteria = [criteria]

    criteria_lines = "\n".join(f"{i+1}. {c}" for i, c in enumerate(criteria)) if criteria else ""
    score_line = f"**当前质量分:** {score:.2f}/1.0" if score is not None else ""

    return f"""---REVISION-REQUEST---
## 修改请求: {title}
**Task ID:** {task_id} | **修改轮次:** {revision_count}/{max_revisions}
{score_line}

### 反馈
{feedback}

### 原始验收标准（请重新对照）
{criteria_lines}

### 要求
- 请针对上述反馈逐条改进
- 保留原有做得好的部分，只改进不足之处
- 完成后在回复末尾写: `TASK-COMPLETE: {task_id}`
---END-REVISION-REQUEST---"""


def parse_task_completion(content: str) -> str | None:
    """从 Bot 回复中提取 TASK-COMPLETE 标记里的 task_id。

    Args:
        content: 消息内容

    Returns:
        task_id 或 None（如果没有完成标记）
    """
    match = re.search(r"TASK-COMPLETE:\s*(\S+)", content)
    return match.group(1) if match else None


def build_thread_context_qc(tasks: list[dict]) -> dict:
    """构建 Thread context 中的 _qc 部分，用于同步任务状态给所有 Bot。

    Args:
        tasks: 活跃任务列表

    Returns:
        _qc context 字典
    """
    active = []
    completed_count = 0
    for t in tasks:
        if t["status"] in ("completed", "failed"):
            completed_count += 1
        else:
            active.append({
                "id": t["id"],
                "title": t["title"],
                "assigned_to": t.get("assigned_to", ""),
                "status": t["status"],
                "quality_score": t.get("quality_score"),
            })

    return {
        "enabled": True,
        "active_tasks": active[:10],  # 限制上下文大小
        "completed_count": completed_count,
    }
