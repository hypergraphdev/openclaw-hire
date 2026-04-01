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

    # 从内容中提取 @mentions，判断是否多人任务
    mentioned = re.findall(r"@([\w\-\u4e00-\u9fff]+)", content)
    # 去重，保留顺序
    seen: set[str] = set()
    executors: list[str] = []
    for name in mentioned:
        if name not in seen and name != assigned_to:
            executors.append(name)
            seen.add(name)

    if executors and assigned_to:
        # 多人任务：assigned_to 是项目经理，@的人是执行者
        role_line = f"**项目经理:** @{assigned_to} | **执行者:** {', '.join(f'@{e}' for e in executors)} | "
    elif assigned_to:
        role_line = f"**分配给:** @{assigned_to} | "
    else:
        role_line = ""

    # ── 多人任务执行者说明 ──
    executor_section = ""
    if executors:
        executor_section = f"""
### 多人协作
- **被 @ 到的执行者:** {', '.join(f'@{e}' for e in executors)}
- 每位执行者请各自认领自己负责的部分，完成后回复结果
- 项目经理负责统筹协调和最终汇总"""

    # ── 发送者身份说明 ──
    assigned_by = task.get("assigned_by", "")
    identity_note = ""
    if assigned_by:
        identity_note = f"""
### 关于发送者身份
本任务由人类主人通过 @{assigned_by} 的身份发送。
当你需要确认或反馈时，回复本群即可，人类主人会看到。"""

    # ── 名字说明 ──
    name_note = """
### 关于名字
在本组织中，每个成员使用的是**组织内名字**（即 @ 后面的名字）。
这个名字可能和成员自己取的实例名称不同——请以组织内名字为准来识别和称呼对方。"""

    return f"""---TASK---
## 任务: {title}
{role_line}**深度要求:** {depth} | **ID:** {task_id}

### 任务描述
{content}

### 验收标准（必须全部满足）
{criteria_lines}
{executor_section}{identity_note}
### 工作流程要求

**第一步：确认收到（必须）**
收到任务后，请先简短回复，表明：
1. 你已收到并理解了任务
2. 你对任务的理解要点（用自己的话概述）
3. 如果有不清楚的地方，在这一步提出所有疑问

**第二步：执行任务**
确认无误后，开始深入完成任务。过程中：
- 如果遇到重大阻碍或方向性问题，可以阶段性反馈进展
- 除非遇到无法继续的问题，否则不要中途停下来等确认——在第一步就把需求搞清楚
- 原则：**开头问清楚，中间少打扰，结尾交成果**

**第三步：提交成果**
- 深度: {depth} — {depth_desc}
- 结构清晰，使用标题和分节组织内容
- 给出具体的数据、示例或证据，而非泛泛而谈
- 完成后在回复末尾写: `TASK-COMPLETE: {task_id}`
{name_note}
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
