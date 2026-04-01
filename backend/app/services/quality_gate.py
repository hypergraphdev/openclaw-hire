"""Quality Gate — AI 驱动的 Bot 回复质量评估。

用轻量 AI 模型（Haiku 级别）评估 Bot 回复是否满足任务的验收标准，
不达标时自动生成修改请求。
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
import logging

logger = logging.getLogger(__name__)

# ── 评估 Prompt ──

EVALUATOR_SYSTEM_PROMPT = """你是一个回复质量评估器。你的工作是评估一个 AI Bot 的回复是否满足指定的任务要求。

你会收到：任务描述、验收标准、深度要求、以及 Bot 的回复。

请对以下维度各打分 0.0-1.0：
- completeness（完整性）: 回复是否覆盖了所有验收标准？
- depth（深度）: 是否匹配要求的深度（shallow/moderate/thorough/exhaustive）？
- specificity（具体性）: 是否给出了具体的数据、示例、证据，还是只有泛泛的描述？
- structure（结构）: 是否组织清晰、易于理解？

请严格输出以下 JSON 格式（不要输出其他内容）：
{
  "overall_score": <float 0.0-1.0>,
  "dimensions": {
    "completeness": <float>,
    "depth": <float>,
    "specificity": <float>,
    "structure": <float>
  },
  "verdict": "PASS" 或 "REVISE" 或 "FAIL",
  "feedback": "<针对 Bot 的具体、可操作的改进建议>",
  "unmet_criteria": ["<未满足的标准1>", ...],
  "strengths": ["<做得好的地方1>", ...]
}

评判标准：
- overall_score >= 0.7 → PASS
- overall_score >= 0.4 且 < 0.7 → REVISE
- overall_score < 0.4 → FAIL
"""


def _build_eval_prompt(task: dict, response: str) -> str:
    """构建评估请求的 user prompt。"""
    criteria = task.get("acceptance_criteria", [])
    if isinstance(criteria, str):
        try:
            criteria = json.loads(criteria)
        except (json.JSONDecodeError, TypeError):
            criteria = [criteria]

    criteria_text = "\n".join(f"- {c}" for c in criteria) if criteria else "- 完整回答任务描述中的问题"

    return f"""## 任务信息
**标题:** {task.get('title', '')}
**深度要求:** {task.get('depth', 'thorough')}

**任务描述:**
{task.get('description', '')}

**验收标准:**
{criteria_text}

## Bot 的回复
{response}

请对这个回复进行质量评估。"""


def evaluate_response(task: dict, response: str, api_key: str) -> dict:
    """调用 AI 模型评估 Bot 回复质量。

    Args:
        task: 任务字典
        response: Bot 的回复内容
        api_key: Anthropic API key

    Returns:
        评估结果字典，包含 overall_score, dimensions, verdict, feedback 等
    """
    if not api_key:
        return {
            "overall_score": 0.0,
            "dimensions": {},
            "verdict": "FAIL",
            "feedback": "未配置评估 API Key",
            "unmet_criteria": [],
            "strengths": [],
        }

    user_prompt = _build_eval_prompt(task, response)

    # 调用 Anthropic Messages API（用 Haiku 级别模型控制成本）
    body = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1024,
        "system": EVALUATOR_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())

        # 提取 text content
        text = ""
        for block in result.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")

        # 解析 JSON
        # 去掉可能的 markdown code block
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        evaluation = json.loads(text)

        # 确保有必要字段
        evaluation.setdefault("overall_score", 0.0)
        evaluation.setdefault("verdict", "FAIL")
        evaluation.setdefault("feedback", "")
        evaluation.setdefault("unmet_criteria", [])
        evaluation.setdefault("strengths", [])
        evaluation.setdefault("dimensions", {})

        return evaluation

    except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
        logger.error("Quality gate evaluation failed: %s", e)
        return {
            "overall_score": 0.0,
            "dimensions": {},
            "verdict": "FAIL",
            "feedback": f"评估过程出错: {e}",
            "unmet_criteria": [],
            "strengths": [],
        }


def should_request_revision(task: dict, evaluation: dict, min_score: float = 0.6) -> bool:
    """判断是否应该发送修改请求。

    Args:
        task: 任务字典
        evaluation: 评估结果
        min_score: 最低通过分数

    Returns:
        True 表示需要修改
    """
    verdict = evaluation.get("verdict", "FAIL")
    score = evaluation.get("overall_score", 0.0)
    revision_count = task.get("revision_count", 0)
    max_revisions = task.get("max_revisions", 2)

    # 已达到最大修改次数，不再要求修改
    if revision_count >= max_revisions:
        return False

    # PASS 不需要修改
    if verdict == "PASS" and score >= min_score:
        return False

    # REVISE 或低分需要修改
    return True
