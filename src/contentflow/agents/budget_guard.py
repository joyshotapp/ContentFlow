"""Budget Guard：預算守衛節點

防護文章生產過程中的資源消耗超標。
- 最大 LLM 呼叫次數：15 次/篇
- 最大成本：$2.00/篇
- 超出 → 標記人工審核，保留目前最佳輸出
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AgentBudget:
    """每篇文章的資源預算（對應計畫 §17.2）"""
    max_llm_calls_per_article: int = 15
    max_cost_per_article: float = 2.0
    max_retry_per_step: int = 3
    max_total_retries: int = 6


DEFAULT_BUDGET = AgentBudget()


def budget_guard_node(state: dict) -> dict:
    """
    預算守衛節點（LangGraph Node）。

    超過任何一項上限 →
    1. 標記 _budget_exceeded = True
    2. 記錄到 agent_decisions
    3. 保留目前最佳輸出（不丟棄 draft）

    Args:
        state: LangGraph ArticleState（以 dict 傳入避免循環引用）

    Returns:
        更新後的 state partial（只含變動欄位）
    """
    budget = DEFAULT_BUDGET
    calls = state.get("total_llm_calls", 0)
    cost = state.get("total_cost", 0.0)

    violations: list[str] = []

    if calls > budget.max_llm_calls_per_article:
        violations.append(
            f"LLM 呼叫次數 {calls} 超過上限 {budget.max_llm_calls_per_article}"
        )
    if cost > budget.max_cost_per_article:
        violations.append(
            f"累計成本 ${cost:.3f} 超過上限 ${budget.max_cost_per_article:.2f}"
        )

    decisions = list(state.get("agent_decisions") or [])

    if violations:
        reason = "；".join(violations)
        decisions.append({
            "step": "budget_guard",
            "decision": "強制停止並標記人工審核",
            "reason": reason,
            "confidence": "rule",
        })
        return {
            "agent_decisions": decisions,
            "_budget_exceeded": True,
        }

    # 預算正常
    decisions.append({
        "step": "budget_guard",
        "decision": "預算檢查通過",
        "reason": (
            f"calls={calls}/{budget.max_llm_calls_per_article}，"
            f"cost=${cost:.3f}/${budget.max_cost_per_article:.2f}"
        ),
        "confidence": "rule",
    })
    return {
        "agent_decisions": decisions,
        "_budget_exceeded": False,
    }


def budget_gate(state: dict) -> str:
    """
    預算條件邊的 routing 函式（LangGraph conditional_edge）

    Returns:
        "ok" 或 "over_budget"
    """
    if state.get("_budget_exceeded", False):
        return "over_budget"
    return "ok"
